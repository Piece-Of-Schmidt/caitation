import sqlite3

import pytest

from backend import zotero_reader


def _db(tmp_path, userdata_version):
    path = tmp_path / "zotero.sqlite"
    con = sqlite3.connect(path)
    con.execute("create table version (schema text primary key, version int not null)")
    con.execute("insert into version values ('userdata', ?)", (userdata_version,))
    con.commit()
    con.close()
    return path


def test_tested_layout_gives_no_warning(tmp_path):
    version = zotero_reader.schema_version(_db(tmp_path, zotero_reader.TESTED_SCHEMA_VERSION))
    assert version == zotero_reader.TESTED_SCHEMA_VERSION
    assert zotero_reader.schema_warning(version) is None


def test_newer_layout_warns(tmp_path):
    version = zotero_reader.schema_version(_db(tmp_path, zotero_reader.TESTED_SCHEMA_VERSION + 3))
    assert "neuer" in zotero_reader.schema_warning(version)


def test_unreadable_layout_names_the_cause(tmp_path):
    # a library whose tables Caitation does not recognise (here: none at all)
    with pytest.raises(zotero_reader.ZoteroSchemaError, match="Format geändert"):
        zotero_reader.read_items(_db(tmp_path, 999))
