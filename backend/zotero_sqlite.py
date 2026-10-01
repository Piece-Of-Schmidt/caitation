"""Reads items out of the copy of Zotero's database that Caitation up to v0.1 kept in
data/zotero_snapshot.sqlite. Used only once, by the upgrade to the local API: it tells
which items are unchanged since they were indexed, so they are not indexed again.
Caitation no longer reads Zotero's own database."""

import sqlite3
from contextlib import closing
from pathlib import Path

from backend import config
from backend.library import ZoteroItem


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


def read_items(db_path: Path) -> list[ZoteroItem]:
    # closing(): release the file handle even on errors
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as con:
        return _read_items(con.cursor())


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
