"""Extracts PDF full text + metadata for every Zotero item, chunks it, embeds it
locally and stores it in a persistent Chroma collection. Skips items that have not
changed since the last run (tracked via data/state.json)."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from backend import config  # noqa: E402  (must run first: sets HF_HOME env var)

import chromadb
import pypdfium2 as pdfium
from sentence_transformers import SentenceTransformer

from backend.documents import extract_sections
from backend.zotero_reader import ZoteroItem, read_items, snapshot_database

COLLECTION_NAME = "zotero_library"

_progress = {"total": 0, "done": 0, "current": "", "status": "idle"}

_embedding_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    """Process-wide embedding model, shared by the indexer and the search side so
    the server holds one copy (~1 GB) instead of two."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _embedding_model


def get_progress() -> dict:
    return dict(_progress)


def _load_state() -> dict:
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    config.STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


HASH_VERSION = 2


def _relative_pdf_path(path: Path) -> str:
    """attachment-key/filename: stays the same when the Zotero data directory moves."""
    try:
        return path.relative_to(config.ZOTERO_STORAGE).as_posix()
    except ValueError:
        return path.as_posix()


def _file_id(path: Path) -> str:
    """Stable id of an attachment file for chunk ids: the Zotero attachment key for
    stored files, a short path hash for linked files (which share folders)."""
    try:
        return path.relative_to(config.ZOTERO_STORAGE).parts[0]
    except ValueError:
        return hashlib.sha256(path.as_posix().encode("utf-8")).hexdigest()[:12]


def _content_hash(item: ZoteroItem, with_file_sizes: bool) -> str:
    h = hashlib.sha256()
    h.update(item.title.encode("utf-8", "ignore"))
    h.update(item.abstract.encode("utf-8", "ignore"))
    h.update("|".join(item.tags).encode("utf-8", "ignore"))
    h.update("|".join(item.notes).encode("utf-8", "ignore"))
    for a in item.annotations:
        h.update(f"{a['text']}|{a['comment']}|{a['page']}".encode("utf-8", "ignore"))
    # documents only contribute when present, so PDF-only items keep their old hash
    files = [("", p) for p in item.pdf_paths] + [("doc:", p) for p in item.documents]
    for prefix, p in files:
        entry = prefix + _relative_pdf_path(p)
        if with_file_sizes:
            try:
                entry += f":{p.stat().st_size}"
            except OSError:
                pass
        h.update(entry.encode("utf-8", "ignore"))
    return h.hexdigest()


def _item_hash(item: ZoteroItem) -> str:
    # Location-independent (relative path + size, no absolute path or mtime), so
    # moving the Zotero data directory does not look like every item changed.
    return _content_hash(item, with_file_sizes=True)


def _migrate_state(state: dict, items: list[ZoteroItem], old_snapshot: Path | None) -> int:
    """One-time upgrade of skip-state entries written with the old, path-dependent
    hash: an item whose content is identical in the previous snapshot is marked
    up to date without re-embedding. Returns the number of entries carried over."""
    legacy = {key for key, entry in state.items() if entry.get("v") != HASH_VERSION}
    if not legacy:
        return 0
    old_items = {}
    if old_snapshot is not None and old_snapshot.exists():
        old_items = {i.key: i for i in read_items(old_snapshot)}
    carried = 0
    for item in items:
        old = old_items.get(item.key)
        if item.key not in legacy or old is None:
            continue
        if _content_hash(old, with_file_sizes=False) == _content_hash(item, with_file_sizes=False):
            state[item.key] = {"hash": _item_hash(item), "v": HASH_VERSION}
            carried += 1
    return carried


_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def _ocr_page(page) -> str:
    bitmap = page.render(scale=200 / 72)  # 200 dpi
    try:
        result, _ = _get_ocr()(bitmap.to_numpy())
    finally:
        bitmap.close()
    if not result:
        return ""
    return "\n".join(line[1] for line in result)


# PDFium reports line ends as \r\n and leaks a few control characters from some fonts
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _page_text(page) -> str:
    textpage = page.get_textpage()
    try:
        text = textpage.get_text_range()
    finally:
        textpage.close()
    return _CONTROL_CHARS.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def _extract_pdf_pages(pdf_path: Path) -> list[str]:
    try:
        pdf = pdfium.PdfDocument(pdf_path)
    except Exception:
        return []
    try:
        pages = [pdf[i] for i in range(len(pdf))]
        texts = [_page_text(page) for page in pages]

        # scanned PDF (no text layer) -> OCR as fallback
        if texts and sum(len(t) for t in texts) / len(texts) < 50:
            try:
                texts = [_ocr_page(page) for page in pages]
            except Exception:
                pass  # keep whatever the text layer gave us
        for page in pages:
            page.close()
        return texts
    except Exception:
        return []
    finally:
        pdf.close()


_SENTENCE_END = re.compile(r"[.!?][\"'“”)\]]?\s")


def _sentence_boundary(text: str, target_end: int, window_start: int) -> int:
    """Moves a chunk end back to the nearest sentence boundary, as long as one
    exists in the back 40% of the window; otherwise keeps the hard cut."""
    search_from = window_start + int((target_end - window_start) * 0.6)
    best = None
    for m in _SENTENCE_END.finditer(text, search_from, target_end):
        best = m.end()
    return best if best is not None else target_end


def _chunk_pages(pages: list[str]) -> list[tuple[str, int]]:
    """Returns list of (chunk_text, starting_page_number). Windows are char-based
    but end on sentence boundaries where possible, so quotes stay intact. Also used for
    unpaginated documents (sections instead of pages); callers then drop the number."""
    full_text = ""
    page_offsets = []
    for page_text in pages:
        page_offsets.append(len(full_text))
        full_text += page_text + "\n"

    chunks = []
    start = 0
    size = config.CHUNK_SIZE_CHARS
    overlap = config.CHUNK_OVERLAP_CHARS
    while start < len(full_text):
        end = min(start + size, len(full_text))
        if end < len(full_text):
            end = _sentence_boundary(full_text, end, start)
        chunk_text = full_text[start:end].strip()
        if chunk_text:
            page_num = 1
            for i, offset in enumerate(page_offsets):
                if offset <= start:
                    page_num = i + 1
                else:
                    break
            chunks.append((chunk_text, page_num))
        if end >= len(full_text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _metadata_text(item: ZoteroItem) -> str:
    parts = [
        f"Titel: {item.title}",
        f"Autoren: {item.authors_str}",
        f"Datum: {item.date}",
        f"Typ: {item.item_type}",
    ]
    if item.abstract:
        parts.append(f"Abstract: {item.abstract}")
    if item.tags:
        parts.append("Tags: " + ", ".join(item.tags))
    if item.notes:
        parts.append("Notizen: " + " | ".join(item.notes))
    return "\n".join(parts)


_FTS_SCHEMA = """
    create virtual table chunks using fts5(
        text, title, authors,
        chunk_id unindexed, item_key unindexed, date unindexed,
        item_type unindexed, page unindexed, chunk_type unindexed
    )
"""


def _fts_rows(ids, documents, metadatas) -> list[tuple]:
    return [
        (
            doc,
            meta["title"],
            meta["authors"],
            chunk_id,
            meta["item_key"],
            meta["date"],
            meta["item_type"],
            meta["page"],
            meta.get("chunk_type", "pdf"),
        )
        for chunk_id, doc, meta in zip(ids, documents, metadatas)
    ]


def rebuild_fts(collection) -> None:
    """Builds the SQLite FTS5 keyword index over all chunks from scratch.
    Written to a temp file first so a running server never sees a half-built index."""
    _progress.update(current="Baue Volltext-Index (BM25)...")
    tmp_path = config.FTS_DB.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)

    con = sqlite3.connect(tmp_path)
    con.execute(_FTS_SCHEMA)

    batch, offset = 2000, 0
    while True:
        result = collection.get(
            limit=batch, offset=offset, include=["documents", "metadatas"]
        )
        if not result["ids"]:
            break
        con.executemany(
            "insert into chunks values (?,?,?,?,?,?,?,?,?)",
            _fts_rows(result["ids"], result["documents"], result["metadatas"]),
        )
        offset += batch

    con.commit()
    con.close()
    for attempt in range(20):
        try:
            os.replace(tmp_path, config.FTS_DB)  # atomic swap
            break
        except PermissionError:  # Windows: a search still has the old index open
            if attempt == 19:
                raise
            time.sleep(0.25)


def update_fts(changes: dict[str, tuple | None]) -> None:
    """Applies per-item changes to the existing FTS index in one transaction:
    item_key -> (ids, documents, metadatas) to replace, or None to delete.
    Far cheaper than a full rebuild when only a few papers changed."""
    _progress.update(current=f"Aktualisiere Volltext-Index ({len(changes)} Einträge)...")
    keys = list(changes)
    con = sqlite3.connect(config.FTS_DB)
    try:
        with con:
            # item_key is an unindexed column, so every delete is a full table scan:
            # do one scan for all changed items instead of one per item
            for start in range(0, len(keys), 500):
                batch = keys[start : start + 500]
                con.execute(
                    f"delete from chunks where item_key in ({','.join('?' * len(batch))})",
                    batch,
                )
            for rows in changes.values():
                if rows is not None:
                    con.executemany(
                        "insert into chunks values (?,?,?,?,?,?,?,?,?)", _fts_rows(*rows)
                    )
    finally:
        con.close()


def run_reindex() -> None:
    _progress.update(status="running", done=0, total=0, current="Lese Zotero-Bibliothek...")
    state = _load_state()
    needs_migration = any(entry.get("v") != HASH_VERSION for entry in state.values())
    previous_snapshot = None
    if needs_migration and config.DB_SNAPSHOT.exists():
        # keep the old snapshot around: it is the reference for the state migration
        previous_snapshot = config.DB_SNAPSHOT.with_suffix(".previous.sqlite")
        shutil.copy2(config.DB_SNAPSHOT, previous_snapshot)
    snapshot = snapshot_database()
    items = read_items(snapshot)
    if needs_migration:
        _progress.update(current="Übernehme unveränderte Einträge...")
        _migrate_state(state, items, previous_snapshot)
        _save_state(state)
        if previous_snapshot is not None:
            previous_snapshot.unlink(missing_ok=True)

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    collection = client.get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )

    fts_changes: dict[str, tuple | None] = {}
    # Items embedded by an earlier run that was interrupted before its keyword-index
    # update: pull their chunks back out of Chroma so they reach the FTS index now.
    for key, entry in state.items():
        if entry.get("fts_pending"):
            got = collection.get(where={"item_key": key}, include=["documents", "metadatas"])
            fts_changes[key] = (got["ids"], got["documents"], got["metadatas"])

    current_keys = {item.key for item in items}
    removed_keys = set(state.keys()) - current_keys
    for key in removed_keys:
        collection.delete(where={"item_key": key})
        del state[key]
        fts_changes[key] = None

    _progress.update(total=len(items))

    for idx, item in enumerate(items):
        _progress.update(done=idx, current=item.title[:80])
        new_hash = _item_hash(item)
        if state.get(item.key, {}).get("hash") == new_hash:
            continue

        collection.delete(where={"item_key": item.key})

        ids, documents, metadatas = [], [], []

        ids.append(f"{item.key}_meta")
        documents.append(_metadata_text(item))
        metadatas.append(
            {
                "item_key": item.key,
                "title": item.title,
                "authors": item.authors_str,
                "date": item.date,
                "item_type": item.item_type,
                "chunk_type": "metadata",
                "page": 0,
            }
        )

        for ann_idx, ann in enumerate(item.annotations):
            content = ann["text"]
            if ann["comment"]:
                content += f"\nKommentar: {ann['comment']}"
            ids.append(f"{item.key}_ann_{ann_idx}")
            documents.append(content)
            metadatas.append(
                {
                    "item_key": item.key,
                    "title": item.title,
                    "authors": item.authors_str,
                    "date": item.date,
                    "item_type": item.item_type,
                    "chunk_type": "annotation",
                    "page": ann["page"],
                }
            )

        sources = [("pdf", path, _extract_pdf_pages) for path in item.pdf_paths]
        sources += [("doc", path, extract_sections) for path in item.documents]
        for kind, path, extract in sources:
            for chunk_idx, (chunk_text, page_num) in enumerate(_chunk_pages(extract(path))):
                ids.append(f"{item.key}_{kind}_{_file_id(path)}_{chunk_idx}")
                documents.append(chunk_text)
                metadatas.append(
                    {
                        "item_key": item.key,
                        "title": item.title,
                        "authors": item.authors_str,
                        "date": item.date,
                        "item_type": item.item_type,
                        "chunk_type": "pdf" if kind == "pdf" else "document",
                        "page": page_num if kind == "pdf" else 0,  # web pages have no pages
                    }
                )

        if documents:
            # loaded lazily: a reindex where nothing changed never pays for the model
            embeddings = get_embedding_model().encode(
                [f"passage: {d}" for d in documents],
                show_progress_bar=False,
                normalize_embeddings=True,
            ).tolist()
            collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        fts_changes[item.key] = (ids, documents, metadatas)

        # fts_pending until the keyword index has this item (see the recovery above)
        state[item.key] = {"hash": new_hash, "v": HASH_VERSION, "fts_pending": True}
        _save_state(state)

    if not config.FTS_DB.exists():
        rebuild_fts(collection)
    elif fts_changes:
        update_fts(fts_changes)
    done = [entry.pop("fts_pending") for entry in state.values() if "fts_pending" in entry]
    if done:
        _save_state(state)
    _progress.update(status="done", done=len(items), current="Fertig")


if __name__ == "__main__":
    start = time.time()
    if "--fts-only" in sys.argv:
        client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        rebuild_fts(client.get_collection(COLLECTION_NAME))
        print("FTS-Index neu gebaut.")
    else:
        run_reindex()
        print(json.dumps(get_progress(), ensure_ascii=False, indent=2))
    print(f"Dauer: {time.time() - start:.1f}s", file=sys.stderr)
