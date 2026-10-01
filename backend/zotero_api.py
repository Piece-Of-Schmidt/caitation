"""Reads the Zotero library through Zotero's local API (http://127.0.0.1:23119/api/, Zotero 7
and newer). This is Zotero's official, read-only interface; unlike its database file it
does not change layout between versions. It needs a running Zotero with the setting
"Allow other applications on this computer to communicate with Zotero" (the Caitation
plugin offers to switch it on)."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from backend import config
from backend.library import ZoteroItem

API_URL = os.environ.get("ZOTERO_API_URL", "http://127.0.0.1:23119/api").rstrip("/")
USER_LIBRARY = "users/0"  # 0 = the local user, whether or not logged in to zotero.org

PDF_TYPE = "application/pdf"
DOCUMENT_TYPES = {"text/html", "application/xhtml+xml", "application/epub+zip", "text/plain"}
STORED_FILE_MODES = {"imported_file", "imported_url"}
# highlights, sticky notes, underlines and text boxes; images and ink carry no text
TEXT_ANNOTATIONS = {"highlight", "note", "underline", "text"}


class ZoteroUnavailable(RuntimeError):
    """Zotero cannot be read right now. reason: "closed", "disabled" or "error"."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


CLOSED = ZoteroUnavailable(
    "closed", "Zotero ist nicht geöffnet. Caitation übernimmt Änderungen, sobald Zotero läuft."
)
DISABLED = ZoteroUnavailable(
    "disabled",
    "Caitation hat noch keinen Lesezugriff auf Zotero. Im Caitation-Plugin auf „Erlauben“ "
    "klicken oder in Zotero unter Einstellungen → Erweitert die Kommunikation mit anderen "
    "Anwendungen auf diesem Computer erlauben.",
)


def _get(path: str, timeout: float = 60) -> tuple[bytes, dict]:
    request = urllib.request.Request(f"{API_URL}/{path}", headers={"Zotero-API-Version": "3"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        if error.code == 403 and "not enabled" in body.lower():
            raise DISABLED from error
        if error.code == 404 and "endpoint" in body.lower():
            raise ZoteroUnavailable(
                "error", "Diese Zotero-Version hat keine lokale Schnittstelle; Caitation braucht Zotero 7 oder neuer."
            ) from error
        raise ZoteroUnavailable("error", f"Zotero meldet HTTP {error.code} für {path}: {body[:200]}") from error
    except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
        raise CLOSED from error


def _get_json(path: str) -> tuple[list | dict, dict]:
    body, headers = _get(path)
    return json.loads(body), headers


def libraries() -> list[dict]:
    """The personal library plus every group library: [{prefix, group_id, name}]."""
    found = [{"prefix": USER_LIBRARY, "group_id": None, "name": "Meine Bibliothek"}]
    try:
        groups, _ = _get_json(f"{USER_LIBRARY}/groups")
    except ZoteroUnavailable as error:
        if error.reason != "error":
            raise
        groups = []  # no group endpoint: personal library only
    for group in groups:
        group_id = group.get("id") or group.get("data", {}).get("id")
        name = group.get("data", {}).get("name") or f"Gruppe {group_id}"
        found.append({"prefix": f"groups/{group_id}", "group_id": int(group_id), "name": name})
    return found


def library_versions() -> dict[str, int]:
    """Current version of every library; it grows with each change in Zotero. Cheap
    (one tiny request per library), so it can be polled to notice changes."""
    versions = {}
    for lib in libraries():
        _, headers = _get(f"{lib['prefix']}/items?limit=1&format=keys")
        versions[lib["prefix"]] = int(_header(headers, "Last-Modified-Version") or 0)
    return versions


def _header(headers: dict, name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _file_url_to_path(url: str) -> Path | None:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme != "file":
        return None
    return Path(urllib.request.url2pathname(urllib.parse.unquote(parsed.path)))


def _attachment_path(prefix: str, attachment: dict) -> Path | None:
    """Where Zotero keeps an attachment's file, as Zotero itself reports it."""
    try:
        body, _ = _get(f"{prefix}/items/{attachment['key']}/file/view/url", timeout=10)
    except ZoteroUnavailable as error:
        if error.reason != "error":
            raise
        return None  # e.g. 404: file not available
    return _file_url_to_path(body.decode("utf-8"))


class _FileResolver:
    """Stored files live in <storage>/<attachment key>/<filename>: after asking Zotero
    for one of them, the others follow without a request each. Linked files (absolute or
    relative to the base directory) are always resolved by Zotero."""

    def __init__(self):
        # start with the folder found in Zotero's settings; corrected by Zotero's answer
        self.storage: Path | None = config.ZOTERO_STORAGE

    def __call__(self, prefix: str, attachment: dict) -> Path | None:
        filename = attachment.get("filename")
        if attachment.get("linkMode") in STORED_FILE_MODES and filename:
            if self.storage is not None:
                candidate = self.storage / attachment["key"] / filename
                if candidate.is_file():
                    return candidate
            path = _attachment_path(prefix, attachment)
            if path is not None and path.parent.name == attachment["key"]:
                self.storage = path.parent.parent
                # chunk ids and hashes use paths relative to the storage folder
                config.ZOTERO_STORAGE = self.storage
            return path
        if attachment.get("linkMode") == "linked_file":
            return _attachment_path(prefix, attachment)
        return None


def _page(label) -> int:
    try:
        return int(label)
    except (TypeError, ValueError):
        return 0


def build_items(objects: list[dict], collections: list[dict], library: dict, resolve) -> list[ZoteroItem]:
    """ZoteroItems from the API's JSON objects of one library. resolve(prefix, attachment)
    returns the attachment's file path or None."""
    data = [o.get("data", o) for o in objects]
    live = [d for d in data if not d.get("deleted")]
    children = defaultdict(list)
    for d in live:
        if d.get("parentItem"):
            children[d["parentItem"]].append(d)
    collection_names = {c["key"]: c.get("data", c).get("name", "") for c in collections}
    group_id = library["group_id"]

    items = []
    for d in live:
        if d["itemType"] in ("attachment", "note", "annotation"):
            continue
        attachments = [c for c in children[d["key"]] if c["itemType"] == "attachment"]
        pdfs, documents = [], []
        for attachment in attachments:
            content_type = attachment.get("contentType")
            if content_type != PDF_TYPE and content_type not in DOCUMENT_TYPES:
                continue
            path = resolve(library["prefix"], attachment)
            if path is None or not path.is_file():
                continue
            (pdfs if content_type == PDF_TYPE else documents).append(path)
        annotations = sorted(
            (a for att in attachments for a in children[att["key"]]
             if a["itemType"] == "annotation" and a.get("annotationType") in TEXT_ANNOTATIONS),
            key=lambda a: a.get("annotationSortIndex", ""),
        )
        items.append(ZoteroItem(
            key=f"g{group_id}:{d['key']}" if group_id else d["key"],
            zotero_key=d["key"],
            group_id=group_id,
            library_name=library["name"],
            item_type=d["itemType"],
            title=d.get("title") or d.get("shortTitle") or "",
            date=d.get("date", ""),
            abstract=d.get("abstractNote", ""),
            creators=[
                (c.get("name") or f"{c.get('firstName', '')} {c.get('lastName', '')}").strip()
                for c in d.get("creators", [])
            ],
            tags=[t["tag"] for t in d.get("tags", [])],
            notes=[c["note"] for c in children[d["key"]] if c["itemType"] == "note" and c.get("note")],
            pdf_paths=pdfs,
            documents=documents,
            collections=[collection_names[k] for k in d.get("collections", []) if k in collection_names],
            annotations=[
                {"text": (a.get("annotationText") or "").strip(),
                 "comment": (a.get("annotationComment") or "").strip(),
                 "page": _page(a.get("annotationPageLabel"))}
                for a in annotations
                if (a.get("annotationText") or "").strip() or (a.get("annotationComment") or "").strip()
            ],
            publication=d.get("publicationTitle", ""),
            doi=d.get("DOI", ""),
            volume=d.get("volume", ""),
            issue=d.get("issue", ""),
            pages=d.get("pages", ""),
        ))
    return items


def read_items() -> tuple[list[ZoteroItem], dict[str, int]]:
    """Every item of every library, and each library's version at the time of reading."""
    items, versions = [], {}
    resolve = _FileResolver()
    for lib in libraries():
        # the local API returns all objects in one response (no paging), without the trash
        objects, headers = _get_json(f"{lib['prefix']}/items")
        collections, _ = _get_json(f"{lib['prefix']}/collections")
        versions[lib["prefix"]] = int(_header(headers, "Last-Modified-Version") or 0)
        items += build_items(objects, collections, lib, resolve)
    return items, versions
