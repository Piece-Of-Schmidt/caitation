"""End-to-end run of the indexer: real Chroma + real keyword index in a temp folder,
a fake embedding model and a fake Zotero library."""

import json
import sqlite3
import threading

import numpy as np
import pytest

from backend import config, indexer
from backend import library as library_store


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
    monkeypatch.setattr(config, "DB_SNAPSHOT", tmp_path / "zotero_snapshot.sqlite")  # none: fresh install
    monkeypatch.setattr(library_store, "LIBRARY_FILE", tmp_path / "library.json")
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: FakeModel())

    page = tmp_path / "storage" / "SNAP0001" / "page.html"
    page.parent.mkdir(parents=True)
    page.write_text("<main><p>Households read grocery prices every week.</p></main>", encoding="utf-8")
    items = [
        make_item(key="AAAA1111", title="Inflation expectations of households", abstract="Survey evidence.",
                  annotations=[{"text": "prices matter most", "comment": "", "page": 3}]),
        make_item(key="BBBB2222", title="Monetary policy in the media", documents=[page]),
    ]
    monkeypatch.setattr(indexer.zotero_api, "read_library", lambda: (items, {"users/0": 7}, []))
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
    assert library_store.versions() == {"users/0": 7}
    assert set(library_store.items_by_key()) == {"AAAA1111", "BBBB2222"}


def test_unchanged_library_does_nothing(library, monkeypatch):
    indexer.run_reindex()
    monkeypatch.setattr(indexer, "get_embedding_model", lambda: pytest.fail("model must not load"))
    indexer.run_reindex()
    assert len(fts_rows()) == 4


def test_removed_and_changed_items_are_updated(library, monkeypatch, make_item):
    indexer.run_reindex()
    changed = make_item(key="AAAA1111", title="Inflation expectations of households", abstract="Survey evidence.")
    # highlight removed, BBBB deleted
    monkeypatch.setattr(indexer.zotero_api, "read_library", lambda: ([changed], {"users/0": 8}, []))

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
    # Zotero unchanged since then, but the watcher resumes the interrupted run
    monkeypatch.setattr(main.zotero_api, "library_versions", library_store.versions)
    assert _watch_once(main, monkeypatch) == 1


class _StopAfterFirstRound(threading.Event):
    def wait(self, timeout=None):
        self.set()
        return True


def _watch_once(main, monkeypatch) -> int:
    """Runs one round of the server's Zotero watcher; returns how many reindexes it started."""
    started = []
    monkeypatch.setattr(main, "_start_reindex", lambda: started.append(1) or True)
    main._watch_zotero(_StopAfterFirstRound())
    return len(started)


def test_watcher_reindexes_when_zotero_changed(library, monkeypatch):
    from backend import main

    indexer.run_reindex()
    monkeypatch.setattr(main.zotero_api, "library_versions", lambda: {"users/0": 7})
    assert _watch_once(main, monkeypatch) == 0  # same version as indexed
    monkeypatch.setattr(main.zotero_api, "library_versions", lambda: {"users/0": 9})
    assert _watch_once(main, monkeypatch) == 1


def test_watcher_waits_while_zotero_is_closed(library, monkeypatch):
    from backend import main

    def closed():
        raise main.zotero_api.CLOSED

    monkeypatch.setattr(main.zotero_api, "library_versions", closed)
    assert _watch_once(main, monkeypatch) == 0
    assert main._zotero["state"] == "closed"


def test_completed_run_clears_the_resume_marker(library):
    indexer.run_reindex()
    assert not indexer.reindex_incomplete()


def test_old_index_is_repaired_in_place(library):
    import chromadb

    indexer.run_reindex()
    collection = chromadb.PersistentClient(path=str(config.CHROMA_DIR)).get_collection(indexer.COLLECTION_NAME)
    # as written by older versions: soft hyphens, and a garbled text layer
    collection.update(ids=["BBBB2222_meta"], documents=["Monetary pol\xadicy in the me￾dia"],
                      embeddings=[[1.0] + [0.0] * 7])
    collection.add(ids=["AAAA1111_pdf_X_0"], documents=["\x17\x8a\x87\x03 \x92\x83\x92\x87\x94\x03 " * 20],
                   metadatas=[{**indexer._chunk_metadata(library[0], "pdf", 1)}], embeddings=[[0.0, 1.0] + [0.0] * 6])
    indexer._text_version_file().unlink()
    assert indexer.needs_text_repair()

    indexer.run_reindex()

    got = collection.get(ids=["BBBB2222_meta"], include=["documents", "embeddings"])
    assert got["documents"] == ["Monetary policy in the media"]
    assert list(got["embeddings"][0]) == [1.0] + [0.0] * 7  # kept, not recomputed
    assert collection.get(ids=["AAAA1111_pdf_X_0"])["ids"] == []  # item re-extracted
    con = sqlite3.connect(config.FTS_DB)
    assert con.execute("select count(*) from chunks where chunks match 'text:policy'").fetchone()[0] == 1
    con.close()
    assert not indexer.needs_text_repair()
