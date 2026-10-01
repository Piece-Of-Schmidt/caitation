import sqlite3

import pytest

from backend import config, indexer


# ---------------------------------------------------------------- chunking


def test_chunks_end_on_sentence_boundaries(monkeypatch):
    monkeypatch.setattr(config, "CHUNK_SIZE_CHARS", 200)
    monkeypatch.setattr(config, "CHUNK_OVERLAP_CHARS", 30)
    sentence = "This is one complete sentence about inflation. "
    chunks = indexer._chunk_pages([sentence * 6, sentence * 6])
    assert len(chunks) > 2
    for text, _page in chunks[:-1]:
        assert text.endswith(".")


def test_chunks_report_their_starting_page(monkeypatch):
    monkeypatch.setattr(config, "CHUNK_SIZE_CHARS", 200)
    monkeypatch.setattr(config, "CHUNK_OVERLAP_CHARS", 30)
    chunks = indexer._chunk_pages(["a " * 150, "b " * 150])
    assert chunks[0][1] == 1
    assert chunks[-1][1] == 2


# ---------------------------------------------------------------- change detection


def test_item_hash_survives_moving_the_zotero_folder(tmp_path, monkeypatch, make_item):
    def pdf_in(storage):
        path = storage / "ATTACH01" / "paper.pdf"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"%PDF same content")
        return path

    old_storage, new_storage = tmp_path / "C" / "storage", tmp_path / "E" / "storage"
    monkeypatch.setattr(config, "ZOTERO_STORAGE", old_storage)
    before = indexer._item_hash(make_item(pdf_paths=[pdf_in(old_storage)]))
    monkeypatch.setattr(config, "ZOTERO_STORAGE", new_storage)
    after = indexer._item_hash(make_item(pdf_paths=[pdf_in(new_storage)]))
    assert before == after


def test_item_hash_changes_with_new_highlight(make_item):
    plain = make_item()
    highlighted = make_item(annotations=[{"text": "key finding", "comment": "", "page": 3}])
    assert indexer._item_hash(plain) != indexer._item_hash(highlighted)


def test_hash_ignores_the_order_zotero_lists_things_in(make_item):
    one = make_item(tags=["b", "a"], notes=["n2", "n1"],
                    annotations=[{"text": "y", "comment": "", "page": 2}, {"text": "x", "comment": "", "page": 1}])
    other = make_item(tags=["a", "b"], notes=["n1", "n2"],
                      annotations=[{"text": "x", "comment": "", "page": 1}, {"text": "y", "comment": "", "page": 2}])
    assert indexer._item_hash(one) == indexer._item_hash(other)


def test_upgrade_carries_over_items_unchanged_since_indexing(tmp_path, monkeypatch, make_item):
    # what v0.1 indexed (its database copy) vs. what Zotero's API reports now
    indexed = {k: make_item(key=k, tags=["x", "y"]) for k in ("SAME", "EDIT", "STALE")}
    now = [make_item(key="SAME", tags=["y", "x"]),  # same content, other tag order
           make_item(key="EDIT", tags=["x", "y"], title="Edited in Zotero"),
           make_item(key="STALE", tags=["x", "y"])]
    monkeypatch.setattr(indexer.zotero_sqlite, "read_items", lambda _path: list(indexed.values()))
    old_snapshot = tmp_path / "zotero_snapshot.sqlite"  # only has to exist; read_items is faked
    old_snapshot.touch()
    state = {
        "SAME": {"hash": indexer._content_hash_v2(indexed["SAME"]), "v": 2},
        "EDIT": {"hash": indexer._content_hash_v2(indexed["EDIT"]), "v": 2},
        # indexed before its last change (e.g. run interrupted): the copy is not what was indexed
        "STALE": {"hash": "older", "v": 2},
    }

    carried = indexer._migrate_state(state, now, old_snapshot)

    assert carried == 1
    assert state["SAME"] == {"hash": indexer._item_hash(now[0]), "v": indexer.HASH_VERSION}
    assert state["EDIT"]["v"] == 2 and state["STALE"]["v"] == 2  # both will be re-indexed


# ---------------------------------------------------------------- keyword index


@pytest.fixture
def fts_db(tmp_path, monkeypatch):
    path = tmp_path / "fts.sqlite"
    monkeypatch.setattr(config, "FTS_DB", path)
    con = sqlite3.connect(path)
    con.execute(indexer._FTS_SCHEMA)
    con.executemany(
        "insert into chunks values (?,?,?,?,?,?,?,?,?)",
        indexer._fts_rows(
            ["A_0", "A_1", "B_0", "C_0"],
            ["alpha one", "alpha two", "beta", "gamma"],
            [_meta("A", 1), _meta("A", 2), _meta("B", 1), _meta("C", 1)],
        ),
    )
    con.commit()
    con.close()
    return path


def _meta(key, page):
    return {"item_key": key, "title": f"T{key}", "authors": "X", "date": "2020",
            "item_type": "journalArticle", "page": page, "chunk_type": "pdf"}


def test_update_fts_replaces_deletes_and_adds(fts_db):
    indexer.update_fts({
        "A": (["A_0"], ["alpha new"], [_meta("A", 1)]),  # changed: 2 chunks -> 1
        "B": None,  # removed from Zotero
        "D": (["D_0"], ["delta"], [_meta("D", 1)]),  # new item
    })
    con = sqlite3.connect(fts_db)
    rows = con.execute("select chunk_id, text from chunks order by chunk_id").fetchall()
    found = con.execute("select chunk_id from chunks where chunks match 'delta'").fetchall()
    con.execute("insert into chunks(chunks) values('integrity-check')")  # raises if corrupt
    con.close()
    assert rows == [("A_0", "alpha new"), ("C_0", "gamma"), ("D_0", "delta")]
    assert found == [("D_0",)]


# ---------------------------------------------------------------- PDF text


class _FakeTextPage:
    def __init__(self, text):
        self.text = text

    def get_text_range(self):
        return self.text

    def close(self):
        pass


class _FakePage:
    def __init__(self, text):
        self.text = text

    def get_textpage(self):
        return _FakeTextPage(self.text)


def test_page_text_normalizes_pdfium_line_ends_and_control_chars():
    raw = "since \r\ncomputers were\x07 able\x01 to\rexecute"
    assert indexer._page_text(_FakePage(raw)) == "since \ncomputers were able to\nexecute"


def test_unreadable_pdf_yields_no_pages(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert indexer._extract_pdf_pages(broken) == []


# ---------------------------------------------------------------- remaining time


def test_item_weight_grows_with_file_size(tmp_path, make_item):
    small, large = tmp_path / "small.pdf", tmp_path / "large.pdf"
    small.write_bytes(b"x" * 1_000)
    large.write_bytes(b"x" * 900_000)
    missing = tmp_path / "gone.pdf"
    assert indexer._item_weight(make_item(pdf_paths=[missing])) == indexer.ITEM_OVERHEAD
    assert indexer._item_weight(make_item(pdf_paths=[large])) > indexer._item_weight(
        make_item(pdf_paths=[small])
    )


def test_eta_extrapolates_from_weighted_progress(monkeypatch):
    clock = iter([1000.0, 1060.0, 1060.0])
    monkeypatch.setattr(indexer.time, "monotonic", lambda: next(clock))
    indexer._start_eta(400)
    assert indexer._eta_seconds() is None  # nothing done yet
    indexer._eta["done"] = 100  # a quarter in 60 s -> three quarters in 180 s
    assert indexer._eta_seconds() == 180


def test_no_eta_in_the_first_seconds(monkeypatch):
    clock = iter([1000.0, 1005.0])
    monkeypatch.setattr(indexer.time, "monotonic", lambda: next(clock))
    indexer._start_eta(10)
    indexer._eta["done"] = 5
    assert indexer._eta_seconds() is None


def test_hash_ignores_the_html_wrapper_around_notes(make_item):
    from_api = make_item(notes=["Comment: Published at ICLR 2020"])
    from_database = make_item(notes=['<div class="zotero-note znv1">Comment: Published at ICLR 2020</div>'])
    assert indexer._item_hash(from_api) == indexer._item_hash(from_database)
    assert indexer._note_text("<p>A &amp; B</p>\n<p>C</p>") == "A & B C"
