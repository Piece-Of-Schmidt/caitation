"""Hybrid search (semantic + BM25 keyword) over the indexed Zotero library plus
optional Claude-based answer synthesis with citable APA references."""

from backend import config  # noqa: E402  (must run first: sets HF_HOME env var)

import logging
import math
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import chromadb
from anthropic import Anthropic
from sentence_transformers import CrossEncoder, SentenceTransformer

from backend.duplicates import dedupe_results
from backend.indexer import COLLECTION_NAME, get_embedding_model
from backend.verification import verify_quotes
from backend.zotero_reader import ZoteroItem, read_items

_reranker: CrossEncoder | None = None
_collection = None
_anthropic_client: Anthropic | None = None
_item_info: dict[str, ZoteroItem] | None = None
_item_info_mtime: float = 0.0

RRF_K = 60  # standard reciprocal-rank-fusion constant


log = logging.getLogger("uvicorn.error")  # shows up in the server console

_retrieval_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="retrieval")
_model_lock = threading.Lock()
_ready = threading.Event()


def _get_model() -> SentenceTransformer:
    with _model_lock:  # warmup thread and first request may race to load it
        return get_embedding_model()


def _get_reranker() -> CrossEncoder | None:
    global _reranker
    if not config.RERANKER_MODEL:
        return None
    if _reranker is None:
        with _model_lock:
            if _reranker is None:
                _reranker = CrossEncoder(config.RERANKER_MODEL)
    return _reranker


def is_ready() -> bool:
    return _ready.is_set()


def warmup() -> None:
    """Loads models, the vector index and item metadata, and pulls the keyword index
    into the OS file cache, so the first search after startup is fast. The data
    directory sits on an HDD, where cold random reads cost seconds per query."""
    try:
        _get_model()
        reranker = _get_reranker()
        if reranker is not None:
            reranker.predict([("warmup", "warmup")], show_progress_bar=False)
        get_item_info()
        if _get_collection().count():
            _vector_search("warmup", 1)
        if config.FTS_DB.exists():
            with open(config.FTS_DB, "rb") as f:
                while f.read(8 << 20):  # one sequential read: fast even on an HDD
                    pass
    finally:
        _ready.set()


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        _collection = client.get_or_create_collection(
            COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
    return _collection


def _get_anthropic_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


def get_item_info() -> dict[str, ZoteroItem]:
    """Item metadata (tags, collections, year, biblio fields, PDF paths) keyed by
    Zotero key. Cached; reloaded when the snapshot database changes."""
    global _item_info, _item_info_mtime
    if not config.DB_SNAPSHOT.exists():
        return {}
    mtime = config.DB_SNAPSHOT.stat().st_mtime
    if _item_info is None or mtime != _item_info_mtime:
        _item_info = {item.key: item for item in read_items(config.DB_SNAPSHOT)}
        _item_info_mtime = mtime
    return _item_info


# ---------------------------------------------------------------- retrieval


def _vector_search(query: str, limit: int, annotations_only: bool = False) -> list[dict]:
    collection = _get_collection()
    if collection.count() == 0:
        return []
    query_embedding = _get_model().encode(
        [f"query: {query}"], normalize_embeddings=True
    )[0].tolist()
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(limit, collection.count()),
        where={"chunk_type": "annotation"} if annotations_only else None,
    )
    return [
        {
            "chunk_id": chunk_id,
            "item_key": meta["item_key"],
            "page": meta["page"],
            "chunk_type": meta.get("chunk_type", "pdf"),
            "text": doc,
            "similarity": 1 - distance,
        }
        for chunk_id, doc, meta, distance in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        )
    ]


def _fts_search(query: str, limit: int, annotations_only: bool = False) -> list[dict]:
    if not config.FTS_DB.exists():
        return []
    tokens = re.findall(r"\w+", query, re.UNICODE)
    if not tokens:
        return []
    match_expr = " OR ".join(f'"{t}"' for t in tokens)
    type_clause = "and chunk_type = 'annotation'" if annotations_only else ""

    con = sqlite3.connect(f"file:{config.FTS_DB}?mode=ro", uri=True)
    try:
        # full chunk text for context/reranking; the short snippet centered on the
        # match is only used for the result-list display
        rows = con.execute(
            f"""
            select chunk_id, item_key, page, chunk_type, text,
                   snippet(chunks, 0, '', '', '…', 50)
            from chunks where chunks match ? {type_clause}
            order by bm25(chunks) limit ?
            """,
            (match_expr, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()

    return [
        {
            "chunk_id": r[0],
            "item_key": r[1],
            "page": r[2],
            "chunk_type": r[3],
            "text": r[4],
            "display": r[5],
        }
        for r in rows
    ]


_LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")
_SENTENCE_START = re.compile(r"[.!?]\s+[A-ZÄÖÜ]")
_SOFT_HYPHEN = re.compile(r"­\s*")  # invisible hyphenation hint, often plus a line break
_LINE_HYPHEN = re.compile(r"(\w)- (?!(?:und|oder|bzw|sowie|als|and|or)\b)([a-zäöüß])")


def _chunk_excerpt(chunk: dict) -> str:
    """Display text for a chunk: the keyword-centered snippet if BM25 found it,
    otherwise the chunk text, which starts at an arbitrary offset (chunk overlap):
    begin at the next sentence if one starts early, else at the next whole word."""
    if chunk.get("display"):
        return chunk["display"]
    text = chunk["text"]
    if not text[:1].isupper():
        sentence = _SENTENCE_START.search(text, 0, 200)
        if sentence:
            text = "…" + text[sentence.end() - 1 :]
        else:
            space = text.find(" ", 0, 40)
            text = "…" + text[space + 1 :] if space > 0 else text
    return text


def _clip(text: str, limit: int) -> str:
    """Normalizes PDF line breaks, rejoins words hyphenated across lines ("Risikoauf-
    schläge"; keeps "Wirtschafts- und …"), and shortens at a word boundary."""
    text = _LONE_SURROGATE.sub("", text)  # broken PDF glyphs would render as �
    text = _SOFT_HYPHEN.sub("", text)
    text = _LINE_HYPHEN.sub(r"\1\2", " ".join(text.split()))
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " …"


def _passes_filters(item: ZoteroItem | None, filters: dict) -> bool:
    if item is None:
        return not filters
    if filters.get("year_from") and (item.year is None or item.year < filters["year_from"]):
        return False
    if filters.get("year_to") and (item.year is None or item.year > filters["year_to"]):
        return False
    if filters.get("item_type") and item.item_type != filters["item_type"]:
        return False
    if filters.get("tag") and filters["tag"] not in item.tags:
        return False
    if filters.get("collection") and filters["collection"] not in item.collections:
        return False
    if filters.get("library") and filters["library"] != item.library_name:
        return False
    return True


ANNOTATION_BOOST = 1.3  # passages the user personally highlighted rank higher

# Ranked candidates per (query, options, index version). Repeating a query, switching
# from "search" to "ask" with the same text, or following a fast preview with the
# reranked version then skips retrieval and/or the slow cross-encoder.
_RANK_CACHE_SIZE = 64
_rank_cache: OrderedDict = OrderedDict()
_rank_cache_lock = threading.Lock()


def _index_version() -> tuple:
    def mtime(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return (mtime(config.FTS_DB), mtime(config.DB_SNAPSHOT))


def _cache_get(key):
    with _rank_cache_lock:
        if key in _rank_cache:
            _rank_cache.move_to_end(key)
            return _rank_cache[key]
    return None


def _cache_put(key, value) -> None:
    with _rank_cache_lock:
        _rank_cache[key] = value
        _rank_cache.move_to_end(key)
        while len(_rank_cache) > _RANK_CACHE_SIZE:
            _rank_cache.popitem(last=False)


def _fused_candidates(query: str, fetch_k: int, annotations_only: bool) -> list[dict]:
    """Semantic + BM25 retrieval (run in parallel), merged via reciprocal rank fusion."""
    key = ("fused", query, fetch_k, annotations_only, _index_version())
    cached = _cache_get(key)
    if cached is not None:
        return cached

    started = time.perf_counter()
    fts_future = _retrieval_pool.submit(_fts_search, query, fetch_k, annotations_only)
    vector_hits = _vector_search(query, fetch_k, annotations_only)
    fts_hits = fts_future.result()
    log.info("retrieval %.2fs (%d semantic, %d keyword): %s",
             time.perf_counter() - started, len(vector_hits), len(fts_hits), query[:60])

    fused: dict[str, dict] = {}
    for hits in (vector_hits, fts_hits):
        for rank, hit in enumerate(hits):
            entry = fused.setdefault(hit["chunk_id"], {**hit, "rrf": 0.0})
            entry["rrf"] += 1 / (RRF_K + rank + 1)
            if "similarity" in hit:
                entry["similarity"] = hit["similarity"]
            if "display" in hit:
                entry.setdefault("display", hit["display"])

    if not annotations_only:
        for entry in fused.values():
            if entry.get("chunk_type") == "annotation":
                entry["rrf"] *= ANNOTATION_BOOST

    ranked = sorted(fused.values(), key=lambda c: c["rrf"], reverse=True)
    _cache_put(key, ranked)
    return ranked


def _ranked_chunks(
    query: str, fetch_k: int, annotations_only: bool, rerank: bool
) -> list[dict]:
    """Candidate chunks with a final rank_score, as fresh dicts (callers may mutate
    them) built on top of the cached lists."""
    candidates = _fused_candidates(query, fetch_k, annotations_only)
    reranker = _get_reranker() if rerank else None
    if reranker is None or not candidates:
        return [{**c, "rank_score": c["rrf"]} for c in candidates]

    key = ("reranked", query, fetch_k, annotations_only, _index_version())
    scores = _cache_get(key)
    if scores is None:
        # Precise re-sorting: the cross-encoder reads (query, chunk) pairs together
        # and scores actual relevance; RRF order is only the pre-selection.
        head = candidates[: config.RERANK_TOP_N]
        started = time.perf_counter()
        raw_scores = reranker.predict(
            [(query, c["text"][:1200]) for c in head], show_progress_bar=False
        )
        scores = {}
        for chunk, raw in zip(head, raw_scores):
            score = 1 / (1 + math.exp(-float(raw)))  # logit -> [0, 1]
            if chunk.get("chunk_type") == "annotation" and not annotations_only:
                score *= ANNOTATION_BOOST
            scores[chunk["chunk_id"]] = score
        _cache_put(key, scores)
        log.info("rerank %.2fs (%d candidates): %s", time.perf_counter() - started, len(head), query[:60])

    # anything beyond the reranked head sorts below it, in RRF order
    return [
        {**chunk, "rank_score": scores.get(chunk["chunk_id"], -1.0 - i)}
        for i, chunk in enumerate(candidates)
    ]


def search(
    query: str, top_k: int = 8, filters: dict | None = None, rerank: bool = True
) -> list[dict]:
    """Hybrid search: semantic + BM25 merged via reciprocal rank fusion, re-sorted by
    the cross-encoder (skipped with rerank=False for a fast preview), deduplicated
    per item, optionally post-filtered by item metadata."""
    filters = {k: v for k, v in (filters or {}).items() if v}
    annotations_only = bool(filters.pop("annotations_only", False))
    fetch_k = 150 if (filters or annotations_only) else 50

    ranked = _ranked_chunks(query, fetch_k, annotations_only, rerank)
    info = get_item_info() if ranked else {}

    chunks_by_item: dict[str, list[dict]] = {}
    for chunk in ranked:
        chunks_by_item.setdefault(chunk["item_key"], []).append(chunk)

    results = []
    for item_key, chunks in chunks_by_item.items():
        item = info.get(item_key)
        if filters and not _passes_filters(item, filters):
            continue
        chunks.sort(key=lambda c: c["rank_score"], reverse=True)
        best = chunks[0]
        if best.get("chunk_type") == "metadata":
            # the raw "Titel: … Autoren: …" block repeats the card header; show the abstract
            snippet = item.abstract if item and item.abstract else ""
        else:
            snippet = _chunk_excerpt(best)
        extra = [c for c in chunks[1:] if c.get("chunk_type") != "metadata"][:2]
        results.append(
            {
                "item_key": item_key,
                "title": item.title if item else "",
                "authors": item.authors_str if item else "",
                "date": item.date if item else "",
                "year": item.year if item else None,
                "item_type": item.item_type if item else "",
                "page": best["page"],
                "chunk_type": best.get("chunk_type", "pdf"),
                "snippet": _clip(snippet, 400),
                "matches": [
                    {"page": c["page"], "snippet": _clip(_chunk_excerpt(c), 300)}
                    for c in extra
                ],
                "score": best.get("similarity"),
                "rank_score": best["rank_score"],
                "zotero_link": item.zotero_link if item else f"zotero://select/library/items/{item_key}",
                "library": item.library_name if item else "",
                "has_pdf": bool(item and item.pdf_paths),
                "_context": best["text"][:3200],
            }
        )

    results.sort(key=lambda r: r["rank_score"], reverse=True)
    return dedupe_results(results)[:top_k]


def related(item_key: str, top_k: int = 6) -> list[dict]:
    """Semantically closest other items, based on the metadata-chunk embedding."""
    collection = _get_collection()
    got = collection.get(ids=[f"{item_key}_meta"], include=["embeddings"])
    if len(got["ids"]) == 0:
        return []
    embedding = got["embeddings"][0]

    result = collection.query(
        query_embeddings=[embedding],
        n_results=min(top_k * 8, collection.count()),
        where={"item_key": {"$ne": item_key}},
    )

    info = get_item_info()
    seen: dict[str, dict] = {}
    for meta, distance in zip(result["metadatas"][0], result["distances"][0]):
        key = meta["item_key"]
        if key in seen:
            continue
        item = info.get(key)
        seen[key] = {
            "item_key": key,
            "title": item.title if item else meta["title"],
            "authors": item.authors_str if item else meta["authors"],
            "year": item.year if item else None,
            "item_type": item.item_type if item else meta["item_type"],
            "page": 0,
            "snippet": (item.abstract[:400] if item and item.abstract else ""),
            "matches": [],
            "score": 1 - distance,
            "zotero_link": item.zotero_link if item else f"zotero://select/library/items/{key}",
            "library": item.library_name if item else "",
            "has_pdf": bool(item and item.pdf_paths),
        }
        if len(seen) >= top_k * 2:
            break
    return dedupe_results(list(seen.values()))[:top_k]


# ---------------------------------------------------------------- answering


def _apa_reference(item: ZoteroItem) -> str:
    parts = [item.authors_str or "o. A."]
    parts.append(f"({item.year})." if item.year else "(o. J.).")
    parts.append(re.sub(r"<[^>]+>", "", item.title) + ".")  # drop Zotero rich-text markup
    if item.publication:
        vol = item.volume
        if item.issue:
            vol = f"{vol}({item.issue})" if vol else f"({item.issue})"
        pub = f"{item.publication}"
        if vol:
            pub += f", {vol}"
        if item.pages:
            pub += f", {item.pages}"
        parts.append(pub + ".")
    if item.doi:
        parts.append(f"https://doi.org/{item.doi}")
    return " ".join(p for p in parts if p)


ANSWER_SYSTEM_PROMPT = """Du hilfst dabei, Paper in einer wissenschaftlichen Literaturdatenbank (Zotero) \
wiederzufinden und Fragen dazu zu beantworten. Du bekommst eine Nutzerfrage und dazu Auszüge \
aus mehreren Papers mit vollständigen bibliografischen Angaben. Antworte auf Deutsch, präzise und knapp.

Zitierregeln:
- Belege jede inhaltliche Aussage mit einem In-Text-Zitat im APA-Stil inkl. Seitenzahl, \
z.B. (Armantier et al., 2016, S. 12).
- Auszüge, die als "vom Nutzer markiert" gekennzeichnet sind, stammen aus persönlichen \
Highlights des Nutzers — zitiere sie bevorzugt, wenn sie zur Frage passen.
- Schließe die Antwort mit einem Abschnitt "Literatur" ab, der die tatsächlich zitierten \
Quellen als vollständige APA-Referenzen auflistet (übernimm die mitgelieferten Referenzzeilen wörtlich).
- Wenn kein Auszug wirklich zur Frage passt, sag das ehrlich, statt zu spekulieren."""

EVIDENCE_SYSTEM_PROMPT = """Du prüfst für eine wissenschaftliche Literaturdatenbank (Zotero), ob eine \
Behauptung durch die Literatur des Nutzers gedeckt ist. Du bekommst eine Behauptung und Auszüge aus \
mehreren Papers mit vollständigen bibliografischen Angaben. Antworte auf Deutsch.

Gehe jede Quelle einzeln durch und ordne sie ein:
- **Stützt die Behauptung** — mit wörtlichem Zitat aus dem Auszug und In-Text-Zitat im APA-Stil inkl. Seitenzahl
- **Widerspricht der Behauptung** — ebenso mit Beleg
- Quellen, die zur Behauptung nichts beitragen, lässt du komplett weg.

Zitiere wörtliche Belege immer als vollständige Sätze. Wenn am zitierten Satz \
Quellenverweise der Autoren hängen (z.B. "(Clerwall 2014; Diakopoulos 2019)"), übernimm \
sie mit ins Zitat — diese Primärquellen sind für die Weiterverfolgung wertvoll.

Struktur der Antwort:
1. Kurzes Fazit in 1-2 Sätzen (Ist die Behauptung gedeckt? Eindeutig, teilweise, umstritten, ungedeckt?)
2. Abschnitt "Stützende Belege" (falls vorhanden)
3. Abschnitt "Widersprechende Belege" (falls vorhanden)
4. Abschnitt "Literatur" mit den vollständigen APA-Referenzen der zitierten Quellen \
(übernimm die mitgelieferten Referenzzeilen wörtlich).

Sei streng: ein Auszug stützt eine Behauptung nur, wenn er sie wirklich inhaltlich trägt, \
nicht wenn er bloß dasselbe Thema behandelt."""


def _prepare_ask(
    query: str,
    top_k: int,
    filters: dict | None,
    history: list[dict] | None,
    mode: str,
) -> tuple[list[dict] | None, list[dict], str, list[dict]]:
    """Shared retrieval + prompt assembly for ask/ask_stream.
    Returns (messages, hits, system_prompt, excerpts); messages is None if there were no
    hits. excerpts are the source texts Claude saw, for checking its quotes afterwards."""
    # Retrieve using the question plus a bit of prior conversation, so follow-up
    # questions like "und was sagt Studie X dazu?" still find the right chunks.
    retrieval_query = query
    if history:
        prior_user = [m["content"] for m in history if m.get("role") == "user"]
        if prior_user:
            retrieval_query = " ".join(prior_user[-2:]) + " " + query

    hits = search(retrieval_query, top_k=top_k, filters=filters)
    if not hits:
        return None, [], "", []

    info = get_item_info()
    context_blocks, excerpts = [], []
    for h in hits:
        item = info.get(h["item_key"])
        reference = _apa_reference(item) if item else f"{h['authors']} - {h['title']}"
        marker = " [vom Nutzer markiert]" if h.get("chunk_type") == "annotation" else ""
        excerpt = h.pop("_context")
        excerpts.append({"item_key": h["item_key"], "title": h["title"], "page": h["page"], "text": excerpt})
        context_blocks.append(
            f"Referenz (APA): {reference}\n"
            f"Auszug (Seite {h['page']}){marker}: {excerpt}"
        )
    context = "\n\n---\n\n".join(context_blocks)

    if mode == "evidence":
        system_prompt = EVIDENCE_SYSTEM_PROMPT
        user_content = f"Behauptung: {query}\n\nGefundene Auszüge:\n\n{context}"
    else:
        system_prompt = ANSWER_SYSTEM_PROMPT
        user_content = f"Frage: {query}\n\nGefundene Auszüge:\n\n{context}"

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in (history or [])
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages.append({"role": "user", "content": user_content})
    return messages, hits, system_prompt, excerpts


_NO_KEY_MSG = (
    "Kein ANTHROPIC_API_KEY konfiguriert. Bitte .env anlegen (siehe .env.example), "
    "um den Frage-Modus zu nutzen. Die reine Suche funktioniert auch ohne Key."
)
_NO_HITS_MSG = "Keine passenden Treffer in der Bibliothek gefunden."


def ask(
    query: str,
    top_k: int = 6,
    filters: dict | None = None,
    history: list[dict] | None = None,
    mode: str = "answer",
) -> dict:
    if not config.ANTHROPIC_API_KEY:
        return {"answer": _NO_KEY_MSG, "sources": []}

    messages, hits, system_prompt, excerpts = _prepare_ask(query, top_k, filters, history, mode)
    if messages is None:
        return {"answer": _NO_HITS_MSG, "sources": []}

    message = _get_anthropic_client().messages.create(
        model=config.ANSWER_MODEL,
        max_tokens=1500,
        system=system_prompt,
        messages=messages,
    )
    answer_text = "".join(
        block.text for block in message.content if block.type == "text"
    )
    return {"answer": answer_text, "sources": hits, "quotes": verify_quotes(answer_text, excerpts)}


def ask_stream(
    query: str,
    top_k: int = 6,
    filters: dict | None = None,
    history: list[dict] | None = None,
    mode: str = "answer",
):
    """Generator of SSE-ready event dicts: first the sources, then text deltas."""
    if not config.ANTHROPIC_API_KEY:
        yield {"type": "sources", "sources": []}
        yield {"type": "delta", "text": _NO_KEY_MSG}
        yield {"type": "done"}
        return

    messages, hits, system_prompt, excerpts = _prepare_ask(query, top_k, filters, history, mode)
    yield {"type": "sources", "sources": hits}
    if messages is None:
        yield {"type": "delta", "text": _NO_HITS_MSG}
        yield {"type": "done"}
        return

    with _get_anthropic_client().messages.stream(
        model=config.ANSWER_MODEL,
        max_tokens=1500,
        system=system_prompt,
        messages=messages,
    ) as stream:
        parts = []
        for text in stream.text_stream:
            parts.append(text)
            yield {"type": "delta", "text": text}
    yield {"type": "quotes", "quotes": verify_quotes("".join(parts), excerpts)}
    yield {"type": "done"}
