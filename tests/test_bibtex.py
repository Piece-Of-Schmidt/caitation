from backend.bibtex import _cite_key, _rich_text_to_latex, items_to_bibtex


def test_zotero_rich_text_becomes_latex():
    title = 'The <i>financial crisis</i> in <span class="nocase">German</span> CO<sub>2</sub>'
    assert _rich_text_to_latex(title) == r"The \textit{financial crisis} in {German} CO\textsubscript{2}"


def test_cite_key_ignores_markup(make_item):
    item = make_item(title="<i>Financial</i> crisis", creators=["Anna Schmidt"], date="2014")
    assert _cite_key(item) == "schmidt2014financial"


def test_export_escapes_and_disambiguates(make_item):
    a = make_item(key="A", title="Prices & Wages", creators=["Anna Schmidt"], date="2014")
    b = make_item(key="B", title="Prices again", creators=["Anna Schmidt"], date="2014")
    bib = items_to_bibtex([a, b])
    assert r"Prices \& Wages" in bib
    keys = [line.split("{", 1)[1].rstrip(",") for line in bib.splitlines() if line.startswith("@")]
    assert len(keys) == len(set(keys)) == 2
