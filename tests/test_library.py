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
