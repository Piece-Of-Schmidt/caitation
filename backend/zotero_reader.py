"""Reads items, metadata and attachment paths out of a Zotero SQLite snapshot."""

import os
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from backend import config


@dataclass
class ZoteroItem:
    key: str
    item_type: str
    title: str
    date: str
    abstract: str
    creators: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    pdf_paths: list[Path] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    annotations: list[dict] = field(default_factory=list)  # {text, comment, page}
    publication: str = ""
    doi: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""

    @property
    def authors_str(self) -> str:
        return ", ".join(self.creators)

    @property
    def year(self) -> int | None:
        import re

        m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", self.date)
        return int(m.group(1)) if m else None


def snapshot_database() -> Path:
    """Copies zotero.sqlite so we can read it even while Zotero is running/has it locked.
    Copies to a temp file and swaps it in atomically: the server may be reading the
    previous snapshot at the same moment and must never see a half-written file."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = config.DB_SNAPSHOT.with_suffix(".tmp")
    shutil.copy2(config.ZOTERO_SQLITE, tmp_path)
    for attempt in range(20):
        try:
            os.replace(tmp_path, config.DB_SNAPSHOT)
            break
        except PermissionError:  # Windows: a reader still has the old snapshot open
            if attempt == 19:
                raise
            time.sleep(0.25)
    return config.DB_SNAPSHOT


def _field_value(cur: sqlite3.Cursor, item_id: int, field_name: str) -> str:
    cur.execute(
        """
        select v.value
        from itemData d
        join fields f on f.fieldID = d.fieldID
        join itemDataValues v on v.valueID = d.valueID
        where d.itemID = ? and f.fieldName = ?
        """,
        (item_id, field_name),
    )
    row = cur.fetchone()
    return row[0] if row else ""


def _creators(cur: sqlite3.Cursor, item_id: int) -> list[str]:
    cur.execute(
        """
        select c.firstName, c.lastName
        from itemCreators ic
        join creators c on c.creatorID = ic.creatorID
        where ic.itemID = ?
        order by ic.orderIndex
        """,
        (item_id,),
    )
    return [f"{first} {last}".strip() for first, last in cur.fetchall()]


def _tags(cur: sqlite3.Cursor, item_id: int) -> list[str]:
    cur.execute(
        """
        select t.name
        from itemTags it
        join tags t on t.tagID = it.tagID
        where it.itemID = ?
        """,
        (item_id,),
    )
    return [r[0] for r in cur.fetchall()]


def _collections(cur: sqlite3.Cursor, item_id: int) -> list[str]:
    cur.execute(
        """
        select c.collectionName
        from collectionItems ci
        join collections c on c.collectionID = ci.collectionID
        where ci.itemID = ?
        """,
        (item_id,),
    )
    return [r[0] for r in cur.fetchall()]


def _annotations(cur: sqlite3.Cursor, item_id: int) -> list[dict]:
    """PDF highlights/underlines/notes the user made in Zotero's reader.
    Annotations hang off the attachment, so we join through itemAttachments."""
    cur.execute(
        """
        select a.text, a.comment, a.pageLabel
        from itemAnnotations a
        join itemAttachments att on att.itemID = a.parentItemID
        where att.parentItemID = ? and a.type in (1, 2, 5, 6)
        order by a.sortIndex
        """,
        (item_id,),
    )
    annotations = []
    for text, comment, page_label in cur.fetchall():
        content = (text or "").strip()
        if not content and not (comment or "").strip():
            continue
        try:
            page = int(page_label)
        except (TypeError, ValueError):
            page = 0
        annotations.append(
            {"text": content, "comment": (comment or "").strip(), "page": page}
        )
    return annotations


def _notes(cur: sqlite3.Cursor, item_id: int) -> list[str]:
    cur.execute("select note from itemNotes where parentItemID = ?", (item_id,))
    return [r[0] for r in cur.fetchall() if r[0]]


def _pdf_paths(cur: sqlite3.Cursor, item_id: int) -> list[Path]:
    cur.execute(
        """
        select i.key, a.path, a.contentType
        from itemAttachments a
        join items i on i.itemID = a.itemID
        where a.parentItemID = ?
        """,
        (item_id,),
    )
    paths = []
    for attachment_key, path, content_type in cur.fetchall():
        if not path or not path.startswith("storage:"):
            continue
        if content_type != "application/pdf":
            continue
        filename = path[len("storage:"):]
        pdf_path = config.ZOTERO_STORAGE / attachment_key / filename
        if pdf_path.exists():
            paths.append(pdf_path)
    return paths


def read_items(db_path: Path) -> list[ZoteroItem]:
    # closing(): release the file handle even on errors, so the snapshot can be replaced
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as con:
        return _read_items(con.cursor())


def _read_items(cur: sqlite3.Cursor) -> list[ZoteroItem]:

    cur.execute(
        """
        select i.itemID, i.key, it.typeName
        from items i
        join itemTypes it on it.itemTypeID = i.itemTypeID
        left join deletedItems d on d.itemID = i.itemID
        where it.typeName not in ('attachment', 'note', 'annotation')
          and d.itemID is null
        """
    )
    rows = cur.fetchall()

    items = []
    for item_id, key, type_name in rows:
        title = _field_value(cur, item_id, "title") or _field_value(cur, item_id, "shortTitle")
        items.append(
            ZoteroItem(
                key=key,
                item_type=type_name,
                title=title,
                date=_field_value(cur, item_id, "date"),
                abstract=_field_value(cur, item_id, "abstractNote"),
                creators=_creators(cur, item_id),
                tags=_tags(cur, item_id),
                notes=_notes(cur, item_id),
                pdf_paths=_pdf_paths(cur, item_id),
                collections=_collections(cur, item_id),
                annotations=_annotations(cur, item_id),
                publication=_field_value(cur, item_id, "publicationTitle"),
                doi=_field_value(cur, item_id, "DOI"),
                volume=_field_value(cur, item_id, "volume"),
                issue=_field_value(cur, item_id, "issue"),
                pages=_field_value(cur, item_id, "pages"),
            )
        )

    return items


if __name__ == "__main__":
    snapshot = snapshot_database()
    items = read_items(snapshot)
    with_pdf = sum(1 for i in items if i.pdf_paths)
    print(f"Gefundene Items: {len(items)}")
    print(f"Davon mit PDF-Anhang: {with_pdf}")
    for i in items[:5]:
        print("-", i.title, "|", i.authors_str, "|", i.date, "| PDFs:", len(i.pdf_paths))
