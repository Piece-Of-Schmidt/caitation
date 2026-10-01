"""End-to-end run of the indexer: real Chroma + real keyword index in a temp folder,
a fake embedding model and a fake Zotero library."""

import json
import sqlite3

import numpy as np
import pytest

from backend import config, indexer


class FakeModel:
    def encode(self, texts, **_kwargs):
        # deterministic, normalized 8-dim vectors; content does not matter here
        vectors = np.array([[len(t) % 7 + 1, *(ord(c) % 5 + 1 for c in t[:7].ljust(7))] for t in texts], float)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


@pytest.fixture
def library(tmp_path, monkeypatch, make_item):
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(config, "FTS_DB", tmp_path / "fts.sqlite")
    monkeypatch.setattr(config, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(config, "ZOTERO_STORAGE", tmp_path / "storage")
    monkeypatch.setattr(indexer, "snapshot_database", lambda: tmp_path / "snapshot.sqlite")
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: FakeModel())

    page = tmp_path / "storage" / "SNAP0001" / "page.html"
    page.parent.mkdir(parents=True)
    page.write_text("<main><p>Households read grocery prices every week.</p></main>", encoding="utf-8")
    items = [
        make_item(key="AAAA1111", title="Inflation expectations of households", abstract="Survey evidence.",
                  annotations=[{"text": "prices matter most", "comment": "", "page": 3}]),
        make_item(key="BBBB2222", title="Monetary policy in the media", documents=[page]),
    ]
    monkeypatch.setattr(indexer, "read_items", lambda _path: items)
    return items


def fts_rows():
    con = sqlite3.connect(config.FTS_DB)
    rows = con.execute("select item_key, chunk_type from chunks order by chunk_id").fetchall()
    con.close()
    return rows


def test_first_run_indexes_metadata_highlights_and_full_text(library):
    indexer.run_reindex()

    assert sorted(fts_rows()) == sorted([
        ("AAAA1111", "metadata"), ("AAAA1111", "annotation"),
        ("BBBB2222", "metadata"), ("BBBB2222", "document"),
    ])
    state = json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    assert set(state) == {"AAAA1111", "BBBB2222"}
    assert not any(entry.get("fts_pending") for entry in state.values())
    assert indexer.get_progress()["status"] == "done"


def test_unchanged_library_does_nothing(library, monkeypatch):
    indexer.run_reindex()
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: pytest.fail("model must not load"))
    indexer.run_reindex()
    assert len(fts_rows()) == 4


def test_removed_and_changed_items_are_updated(library, monkeypatch, make_item):
    indexer.run_reindex()
    changed = make_item(key="AAAA1111", title="Inflation expectations of households", abstract="Survey evidence.")
    monkeypatch.setattr(indexer, "read_items", lambda _path: [changed])  # highlight removed, BBBB deleted

    indexer.run_reindex()

    assert fts_rows() == [("AAAA1111", "metadata")]
    assert set(json.loads(config.STATE_FILE.read_text(encoding="utf-8"))) == {"AAAA1111"}


def test_interrupted_run_is_resumed_on_next_start(library, monkeypatch):
    from backend import main

    def crash(*_args):
        raise KeyboardInterrupt  # e.g. the window was closed during the full-text phase

    monkeypatch.setattr(indexer, "_fulltext_chunks", crash)
    with pytest.raises(KeyboardInterrupt):
        indexer.run_reindex()
    assert indexer.reindex_incomplete()
    assert main._snapshot_stale()  # -> the server restarts the reindex


def test_completed_run_clears_the_resume_marker(library):
    indexer.run_reindex()
    assert not indexer.reindex_incomplete()
