import zipfile
from pathlib import Path

from backend import config, indexer
from backend.documents import extract_sections, html_to_text
from backend.zotero_reader import resolve_attachment_path

STORAGE = Path("/zotero/storage")
BASE = Path("/papers")


# ---------------------------------------------------------------- attachment paths


def test_stored_file_lives_in_its_attachment_folder():
    assert resolve_attachment_path("ABC123", "storage:paper.pdf", 1, STORAGE, BASE) == STORAGE / "ABC123" / "paper.pdf"


def test_linked_file_relative_to_base_directory():
    path = resolve_attachment_path("ABC123", "attachments:Econ/paper.pdf", 2, STORAGE, BASE)
    assert path == BASE / "Econ" / "paper.pdf"


def test_relative_link_without_base_directory_is_skipped():
    assert resolve_attachment_path("ABC123", "attachments:Econ/paper.pdf", 2, STORAGE, None) is None


def test_absolute_linked_file():
    assert resolve_attachment_path("ABC123", "/home/me/paper.pdf", 2, STORAGE, BASE) == Path("/home/me/paper.pdf")


def test_linked_url_has_no_file():
    assert resolve_attachment_path("ABC123", None, 3, STORAGE, BASE) is None


def test_group_items_link_to_their_group(make_item):
    item = make_item(key="g4711:ABCD1234", zotero_key="ABCD1234", group_id=4711)
    assert item.zotero_link == "zotero://select/groups/4711/items/ABCD1234"
    assert make_item(key="ABCD1234").zotero_link == "zotero://select/library/items/ABCD1234"


# ---------------------------------------------------------------- document text


def test_html_text_drops_scripts_and_page_chrome():
    html = """<html><head><style>p{}</style><script>var x = 1;</script></head><body>
      <nav>Home | About</nav><header>Site name</header>
      <article><h1>Inflation &amp; News</h1><p>Households   read
      prices.</p><p>Second<br>line</p></article><footer>Imprint</footer></body></html>"""
    assert html_to_text(html) == "Inflation & News\nHouseholds read prices.\nSecond\nline"


def test_epub_chapters_in_reading_order(tmp_path):
    epub = tmp_path / "book.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
            <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""")
        z.writestr("OEBPS/content.opf", """<?xml version="1.0"?>
            <package xmlns="http://www.idpf.org/2007/opf"><manifest>
              <item id="c2" href="text/ch2.xhtml"/><item id="c1" href="text/ch%201.xhtml"/>
            </manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>""")
        z.writestr("OEBPS/text/ch 1.xhtml", "<html><body><p>First chapter.</p></body></html>")
        z.writestr("OEBPS/text/ch2.xhtml", "<html><body><p>Second chapter.</p></body></html>")
    assert extract_sections(epub) == ["First chapter.", "Second chapter."]


def test_plain_text_and_unreadable_files(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("Just text.", encoding="utf-8")
    assert extract_sections(txt) == ["Just text."]
    broken = tmp_path / "broken.epub"
    broken.write_bytes(b"not a zip")
    assert extract_sections(broken) == []


# ---------------------------------------------------------------- change detection


def test_pdf_only_items_keep_their_hash_and_documents_count(tmp_path, monkeypatch, make_item):
    monkeypatch.setattr(config, "ZOTERO_STORAGE", tmp_path)
    snapshot = tmp_path / "SNAP1234" / "page.html"
    snapshot.parent.mkdir()
    snapshot.write_text("<p>web page</p>", encoding="utf-8")
    pdf_only = make_item()
    with_doc = make_item(documents=[snapshot])
    assert indexer._item_hash(pdf_only) == indexer._content_hash(make_item(), with_file_sizes=True)
    assert indexer._item_hash(with_doc) != indexer._item_hash(pdf_only)


def test_file_ids_keep_attachment_keys_and_hash_linked_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ZOTERO_STORAGE", tmp_path / "storage")
    assert indexer._file_id(tmp_path / "storage" / "ATTACH01" / "paper.pdf") == "ATTACH01"
    linked_a = indexer._file_id(tmp_path / "Papers" / "a.pdf")
    linked_b = indexer._file_id(tmp_path / "Papers" / "b.pdf")
    assert linked_a != linked_b and len(linked_a) == 12


def test_html_prefers_main_content_over_page_chrome():
    article = "<p>" + "Real article text. " * 40 + "</p>"
    html = f"<body><div>Impact Factor: 2.7</div><div>Skip to main content</div><main>{article}</main></body>"
    text = html_to_text(html)
    assert text.startswith("Real article text.")
    assert "Impact Factor" not in text
