from pathlib import Path

from backend import library


def test_library_survives_a_round_trip(tmp_path, monkeypatch, make_item):
    monkeypatch.setattr(library, "LIBRARY_FILE", tmp_path / "library.json")
    item = make_item(key="g7:ABC", zotero_key="ABC", group_id=7, library_name="Gruppe",
                     pdf_paths=[Path("/x/paper.pdf")], annotations=[{"text": "t", "comment": "", "page": 3}])
    assert library.items_by_key() == {} and library.versions() == {}

    library.save([item], {"users/0": 5, "groups/7": 2})

    assert library.items_by_key() == {"g7:ABC": item}
    assert library.versions() == {"users/0": 5, "groups/7": 2}
    assert library.items_by_key()["g7:ABC"].zotero_link == "zotero://select/groups/7/items/ABC"


def test_subcollections_belong_to_their_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "LIBRARY_FILE", tmp_path / "library.json")
    tree = [{"key": "A", "name": "Makro", "parent": None, "library": "Meine Bibliothek"},
            {"key": "B", "name": "Inflation", "parent": "A", "library": "Meine Bibliothek"},
            {"key": "C", "name": "Erwartungen", "parent": "B", "library": "Meine Bibliothek"},
            {"key": "D", "name": "Medien", "parent": None, "library": "Meine Bibliothek"}]
    library.save([], {"users/0": 1}, tree)
    assert library.collection_with_descendants("A") == {"A", "B", "C"}
    assert library.collection_with_descendants("D") == {"D"}


def test_library_from_an_older_version_is_read_again(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "LIBRARY_FILE", tmp_path / "library.json")
    assert not library.outdated()  # nothing stored yet: nothing to refresh
    (tmp_path / "library.json").write_text('{"format": 1, "versions": {}, "items": []}', encoding="utf-8")
    assert library.outdated()
