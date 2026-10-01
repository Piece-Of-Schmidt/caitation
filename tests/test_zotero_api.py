"""The local-API reader against a fake Zotero: a small HTTP server answering like
Zotero's local API (JSON in the Web API v3 format)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend import config, zotero_api


def _obj(data: dict) -> dict:
    return {"key": data["key"], "version": 5, "data": {"version": 5, **data}}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    root = tmp_path / "Zotero" / "storage"
    for key, name in [("ATTPDF01", "paper.pdf"), ("ATTWEB01", "page.html"), ("GRPATT01", "g.pdf")]:
        (root / key).mkdir(parents=True)
        (root / key / name).write_bytes(b"x")
    linked = tmp_path / "Papers" / "linked.pdf"
    linked.parent.mkdir()
    linked.write_bytes(b"x")
    monkeypatch.setattr(config, "ZOTERO_STORAGE", tmp_path / "elsewhere")  # wrong guess on purpose
    return root, linked


def _library(storage):
    root, linked = storage
    items = [
        _obj({"key": "ITEM0001", "itemType": "journalArticle", "title": "Narratives",
              "date": "2021", "abstractNote": "Abstract.", "publicationTitle": "JEP", "DOI": "10.1/x",
              "creators": [{"creatorType": "author", "firstName": "Robert", "lastName": "Shiller"},
                           {"creatorType": "author", "name": "OECD"}],
              "tags": [{"tag": "economics"}, {"tag": "media", "type": 1}],
              "collections": ["COLL0001"]}),
        _obj({"key": "NOTE0001", "itemType": "note", "parentItem": "ITEM0001", "note": "<p>my note</p>"}),
        _obj({"key": "ATTPDF01", "itemType": "attachment", "parentItem": "ITEM0001", "linkMode": "imported_file",
              "contentType": "application/pdf", "filename": "paper.pdf"}),
        _obj({"key": "ATTWEB01", "itemType": "attachment", "parentItem": "ITEM0001", "linkMode": "imported_url",
              "contentType": "text/html", "filename": "page.html"}),
        _obj({"key": "ATTLNK01", "itemType": "attachment", "parentItem": "ITEM0001", "linkMode": "linked_file",
              "contentType": "application/pdf", "path": "attachments:linked.pdf"}),
        _obj({"key": "ATTTRSH1", "itemType": "attachment", "parentItem": "ITEM0001", "linkMode": "imported_file",
              "contentType": "application/pdf", "filename": "gone.pdf", "deleted": 1}),
        _obj({"key": "ANNO0002", "itemType": "annotation", "parentItem": "ATTPDF01", "annotationType": "highlight",
              "annotationText": "second", "annotationComment": "", "annotationPageLabel": "7",
              "annotationSortIndex": "00006|000100|00200"}),
        _obj({"key": "ANNO0001", "itemType": "annotation", "parentItem": "ATTPDF01", "annotationType": "highlight",
              "annotationText": " first ", "annotationComment": "why", "annotationPageLabel": "iv",
              "annotationSortIndex": "00001|000100|00200"}),
        _obj({"key": "ANNO0003", "itemType": "annotation", "parentItem": "ATTPDF01", "annotationType": "image",
              "annotationText": "", "annotationComment": "", "annotationSortIndex": "00002|000000|00000"}),
        _obj({"key": "STANDNOT", "itemType": "note", "note": "<p>standalone</p>"}),
        _obj({"key": "TRASHED1", "itemType": "book", "title": "In the trash", "deleted": 1}),
    ]
    files = {
        "users/0/items/ATTPDF01/file/view/url": (root / "ATTPDF01" / "paper.pdf").as_uri(),
        "users/0/items/ATTLNK01/file/view/url": linked.as_uri(),
        "groups/42/items/GRPATT01/file/view/url": (root / "GRPATT01" / "g.pdf").as_uri(),
    }
    group_items = [
        _obj({"key": "GRPITEM1", "itemType": "book", "title": "Group book"}),
        _obj({"key": "GRPATT01", "itemType": "attachment", "parentItem": "GRPITEM1", "linkMode": "imported_file",
              "contentType": "application/pdf", "filename": "g.pdf"}),
    ]
    return {
        "users/0/groups": [{"id": 42, "data": {"id": 42, "name": "Lehrstuhl"}}],
        "users/0/items": items,
        "users/0/collections": [{"key": "COLL0001", "data": {"key": "COLL0001", "name": "Narrative"}}],
        "groups/42/items": group_items,
        "groups/42/collections": [],
        **files,
    }


@pytest.fixture
def fake_zotero(monkeypatch):
    state = {"routes": {}, "status": 200, "body": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0].removeprefix("/api/")
            if state["status"] != 200:
                self._send(state["status"], state["body"])
            elif path in state["routes"]:
                value = state["routes"][path]
                self._send(200, value if isinstance(value, str) else json.dumps(value))
            else:
                self._send(404, "Not found")

        def _send(self, status, body):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Last-Modified-Version", "123" if "groups/42" not in self.path else "9")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(zotero_api, "API_URL", f"http://127.0.0.1:{server.server_port}/api")
    yield state
    server.shutdown()


def test_reads_items_attachments_highlights_and_groups(fake_zotero, storage):
    root, linked = storage
    fake_zotero["routes"] = _library(storage)

    items, versions = zotero_api.read_items()

    assert versions == {"users/0": 123, "groups/42": 9}
    by_key = {i.key: i for i in items}
    assert set(by_key) == {"ITEM0001", "g42:GRPITEM1"}  # no notes, attachments, trash
    item = by_key["ITEM0001"]
    assert item.creators == ["Robert Shiller", "OECD"]
    assert item.tags == ["economics", "media"]
    assert item.collections == ["Narrative"]
    assert item.notes == ["<p>my note</p>"]
    assert item.pdf_paths == [root / "ATTPDF01" / "paper.pdf", linked]  # trashed PDF left out
    assert item.documents == [root / "ATTWEB01" / "page.html"]
    assert item.annotations == [  # by position in the PDF; image annotation skipped
        {"text": "first", "comment": "why", "page": 0},
        {"text": "second", "comment": "", "page": 7},
    ]
    assert (item.publication, item.doi, item.date) == ("JEP", "10.1/x", "2021")
    group_item = by_key["g42:GRPITEM1"]
    assert (group_item.zotero_key, group_item.group_id, group_item.library_name) == ("GRPITEM1", 42, "Lehrstuhl")
    assert group_item.pdf_paths == [root / "GRPATT01" / "g.pdf"]
    assert config.ZOTERO_STORAGE == root  # learned from Zotero, used for stable chunk ids


def test_library_versions_are_cheap_to_poll(fake_zotero, storage):
    fake_zotero["routes"] = _library(storage)
    assert zotero_api.library_versions() == {"users/0": 123, "groups/42": 9}


def test_disabled_local_api_is_reported_as_such(fake_zotero):
    fake_zotero.update(status=403, body="Local API is not enabled")
    with pytest.raises(zotero_api.ZoteroUnavailable) as error:
        zotero_api.read_items()
    assert error.value.reason == "disabled"


def test_closed_zotero_is_reported_as_such(monkeypatch):
    monkeypatch.setattr(zotero_api, "API_URL", "http://127.0.0.1:9/api")  # nothing listens there
    with pytest.raises(zotero_api.ZoteroUnavailable) as error:
        zotero_api.library_versions()
    assert error.value.reason == "closed"


def test_file_urls_become_paths(tmp_path):
    path = tmp_path / "Ordner mit Ü" / "paper.pdf"
    assert zotero_api._file_url_to_path(path.as_uri()) == path
    assert zotero_api._file_url_to_path("https://example.org/x.pdf") is None
