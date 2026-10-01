import pytest

from backend.library import ZoteroItem


@pytest.fixture
def make_item():
    def _make(key="ABCD1234", title="A Title", **fields):
        defaults = dict(item_type="journalArticle", date="2021-05-01", abstract="")
        defaults.update(fields)
        return ZoteroItem(key=key, title=title, **defaults)

    return _make
