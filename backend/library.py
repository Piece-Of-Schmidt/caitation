"""The Zotero library as Caitation last saw it: items read through Zotero's local API,
kept in data/library.json so search, filters and the dashboard keep working while
Zotero is closed."""

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend import config

LIBRARY_FILE = config.DATA_DIR / "library.json"
FORMAT_VERSION = 2  # 2: collection hierarchy, collection keys per item


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
    collections: list[str] = field(default_factory=list)  # names, for display and stats
    # keys of the item's collections, qualified like item keys ("g<groupID>:<KEY>" in groups)
    collection_keys: list[str] = field(default_factory=list)
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
        m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", self.date)
        return int(m.group(1)) if m else None


def _to_json(item: ZoteroItem) -> dict:
    data = asdict(item)
    data["pdf_paths"] = [str(p) for p in item.pdf_paths]
    data["documents"] = [str(p) for p in item.documents]
    return data


def _from_json(data: dict) -> ZoteroItem:
    data = dict(data)
    data["pdf_paths"] = [Path(p) for p in data.get("pdf_paths", [])]
    data["documents"] = [Path(p) for p in data.get("documents", [])]
    return ZoteroItem(**data)


def save(items: list[ZoteroItem], versions: dict[str, int], collections: list[dict] | None = None) -> None:
    """Writes the library atomically (readers never see a half-written file).
    collections: [{key, name, parent, library}] with qualified keys, parent None at top."""
    payload = {"format": FORMAT_VERSION, "versions": versions, "collections": collections or [],
               "items": [_to_json(i) for i in items]}
    tmp = LIBRARY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, LIBRARY_FILE)


_cache: dict = {}
_cache_lock = threading.Lock()


def _load() -> dict:
    try:
        mtime = LIBRARY_FILE.stat().st_mtime
    except OSError:
        return {"versions": {}, "items": {}, "collections": [], "format": FORMAT_VERSION}
    with _cache_lock:
        if _cache.get("mtime") != mtime:
            payload = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
            items = [_from_json(d) for d in payload.get("items", [])]
            _cache.update(mtime=mtime, versions=payload.get("versions", {}),
                          items={i.key: i for i in items}, collections=payload.get("collections", []),
                          format=payload.get("format", 1))
        return _cache


def items_by_key() -> dict[str, ZoteroItem]:
    """All items keyed by Caitation key; reloaded when the library file changes."""
    return _load()["items"]


def versions() -> dict[str, int]:
    """Zotero's library version per library ("users/0", "groups/<id>") at the last read."""
    return dict(_load()["versions"])


def collections() -> list[dict]:
    """The collection tree: [{key, name, parent, library}]."""
    return list(_load()["collections"])


def outdated() -> bool:
    """Stored by an older Caitation that kept less information: read Zotero again."""
    return bool(LIBRARY_FILE.exists()) and _load()["format"] < FORMAT_VERSION


def collection_with_descendants(key: str) -> set[str]:
    """A collection key plus the keys of all collections below it."""
    children: dict[str | None, list[str]] = {}
    for c in collections():
        children.setdefault(c["parent"], []).append(c["key"])
    found, todo = set(), [key]
    while todo:
        current = todo.pop()
        if current not in found:
            found.add(current)
            todo.extend(children.get(current, []))
    return found


def mtime() -> float:
    """Changes whenever the stored library does; for caches built on top of it."""
    try:
        return LIBRARY_FILE.stat().st_mtime
    except OSError:
        return 0.0
