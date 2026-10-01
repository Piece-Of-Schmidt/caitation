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
    # other full-text attachments: web page snapshots (HTML), EPUBs, plain text
    documents: list[Path] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    annotations: list[dict] = field(default_factory=list)  # {text, comment, page}
    publication: str = ""
    doi: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    # group libraries: Zotero keys are only unique per library, so group items get a
    # qualified key "g<groupID>:<KEY>"; items of the personal library keep the plain key
    zotero_key: str = ""
    group_id: int | None = None
    library_name: str = ""

    @property
    def zotero_link(self) -> str:
        if self.group_id:
            return f"zotero://select/groups/{self.group_id}/items/{self.zotero_key or self.key}"
        return f"zotero://select/library/items/{self.zotero_key or self.key}"

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


LINK_MODE_LINKED_FILE = 2
DOCUMENT_TYPES = {"text/html", "application/xhtml+xml", "application/epub+zip", "text/plain"}


def resolve_attachment_path(
    attachment_key: str,
    path: str | None,
    link_mode: int,
    storage_dir: Path,
    base_dir: Path | None,
) -> Path | None:
    """File location of an attachment, or None for links without a file.

    - stored files:   "storage:paper.pdf"     -> <storage>/<attachment key>/paper.pdf
    - linked, relative to Zotero's base directory: "attachments:Papers/x.pdf"
    - linked, absolute: "C:\\Papers\\x.pdf" or "/home/me/x.pdf"
    """
    if not path:
        return None
    if path.startswith("storage:"):
        return storage_dir / attachment_key / path[len("storage:"):]
    if path.startswith("attachments:"):
        return base_dir / path[len("attachments:"):] if base_dir else None
    if link_mode == LINK_MODE_LINKED_FILE:
        return Path(path)
    return None


def _attachments(cur: sqlite3.Cursor, item_id: int) -> tuple[list[Path], list[Path]]:
    """Existing (PDF files, other full-text documents) attached to an item."""
    cur.execute(
        """
        select i.key, a.path, a.contentType, a.linkMode
        from itemAttachments a
        join items i on i.itemID = a.itemID
        left join deletedItems d on d.itemID = a.itemID
        where a.parentItemID = ? and d.itemID is null
        """,
        (item_id,),
    )
    pdfs, documents = [], []
    for attachment_key, path, content_type, link_mode in cur.fetchall():
        if content_type != "application/pdf" and content_type not in DOCUMENT_TYPES:
            continue
        file = resolve_attachment_path(
            attachment_key, path, link_mode, config.ZOTERO_STORAGE, config.ZOTERO_BASE_ATTACHMENT_DIR
        )
        if file is None or not file.is_file():
            continue
        (pdfs if content_type == "application/pdf" else documents).append(file)
    return pdfs, documents


def _libraries(cur: sqlite3.Cursor) -> dict[int, tuple[int | None, str]]:
    """libraryID -> (groupID or None for the personal library, display name)."""
    cur.execute(
        """
        select l.libraryID, l.type, g.groupID, g.name
        from libraries l left join groups g on g.libraryID = l.libraryID
        """
    )
    libraries = {}
    for library_id, library_type, group_id, name in cur.fetchall():
        if library_type == "group" and group_id is not None:
            libraries[library_id] = (group_id, name or f"Gruppe {group_id}")
        else:
            libraries[library_id] = (None, "Meine Bibliothek")
    return libraries


# Zotero's database layout ("userdata" schema version) this reader was written and tested
# against (Zotero 9.0.6). Zotero does not promise a stable layout: a newer library gets a
# warning, and if reading then fails, the error names the likely cause.
TESTED_SCHEMA_VERSION = 125


class ZoteroSchemaError(RuntimeError):
    pass


def _schema_version(cur: sqlite3.Cursor) -> int | None:
    try:
        row = cur.execute("select version from version where schema = 'userdata'").fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def schema_version(db_path: Path) -> int | None:
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as con:
        return _schema_version(con.cursor())


def schema_warning(version: int | None) -> str | None:
    if version is not None and version > TESTED_SCHEMA_VERSION:
        return (
            "Deine Zotero-Version ist neuer als die, mit der Caitation getestet wurde "
            f"(Datenbankformat {version}, getestet bis {TESTED_SCHEMA_VERSION}). Falls Einträge "
            "fehlen oder die Indexierung scheitert, bitte Caitation aktualisieren."
        )
    return None


def read_items(db_path: Path) -> list[ZoteroItem]:
    # closing(): release the file handle even on errors, so the snapshot can be replaced
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as con:
        cur = con.cursor()
        try:
            return _read_items(cur)
        except sqlite3.Error as error:
            version = _schema_version(cur)
            raise ZoteroSchemaError(
                f"Die Zotero-Datenbank ließ sich nicht lesen ({error}). Wahrscheinlich hat "
                f"Zotero ihr Format geändert (Datenbankformat {version}, getestet bis "
                f"{TESTED_SCHEMA_VERSION}); bitte Caitation aktualisieren."
            ) from error


def _read_items(cur: sqlite3.Cursor) -> list[ZoteroItem]:

    libraries = _libraries(cur)
    cur.execute(
        """
        select i.itemID, i.key, it.typeName, i.libraryID
        from items i
        join itemTypes it on it.itemTypeID = i.itemTypeID
        left join deletedItems d on d.itemID = i.itemID
        where it.typeName not in ('attachment', 'note', 'annotation')
          and d.itemID is null
        """
    )
    rows = cur.fetchall()

    items = []
    for item_id, key, type_name, library_id in rows:
        group_id, library_name = libraries.get(library_id, (None, "Meine Bibliothek"))
        title = _field_value(cur, item_id, "title") or _field_value(cur, item_id, "shortTitle")
        pdfs, documents = _attachments(cur, item_id)
        items.append(
            ZoteroItem(
                key=f"g{group_id}:{key}" if group_id else key,
                zotero_key=key,
                group_id=group_id,
                library_name=library_name,
                item_type=type_name,
                title=title,
                date=_field_value(cur, item_id, "date"),
                abstract=_field_value(cur, item_id, "abstractNote"),
                creators=_creators(cur, item_id),
                tags=_tags(cur, item_id),
                notes=_notes(cur, item_id),
                pdf_paths=pdfs,
                documents=documents,
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
    with_docs = sum(1 for i in items if i.documents)
    print(f"Gefundene Items: {len(items)}")
    print(f"Davon mit PDF-Anhang: {with_pdf}, mit Webseite/EPUB/Text: {with_docs}")
    for i in items[:5]:
        print("-", i.title, "|", i.authors_str, "|", i.date, "| PDFs:", len(i.pdf_paths))
