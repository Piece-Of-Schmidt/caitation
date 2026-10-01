"""Generates BibTeX entries from Zotero item metadata."""

import re

from backend.library import ZoteroItem

_TYPE_MAP = {
    "journalArticle": "article",
    "book": "book",
    "bookSection": "incollection",
    "conferencePaper": "inproceedings",
    "thesis": "phdthesis",
    "report": "techreport",
    "preprint": "unpublished",
    "manuscript": "unpublished",
}


def _escape(value: str) -> str:
    return value.replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")


# Zotero's rich-text title markup -> LaTeX; <span class="nocase"> means "keep this
# capitalization", which is exactly what BibTeX braces do.
_RICH_TEXT = [
    (re.compile(r"<i>(.*?)</i>", re.S), r"\\textit{\1}"),
    (re.compile(r"<b>(.*?)</b>", re.S), r"\\textbf{\1}"),
    (re.compile(r"<sup>(.*?)</sup>", re.S), r"\\textsuperscript{\1}"),
    (re.compile(r"<sub>(.*?)</sub>", re.S), r"\\textsubscript{\1}"),
    (re.compile(r'<span class="nocase">(.*?)</span>', re.S), r"{\1}"),
]


def _rich_text_to_latex(title: str) -> str:
    for pattern, replacement in _RICH_TEXT:
        title = pattern.sub(replacement, title)
    return re.sub(r"<[^>]+>", "", title)


def _cite_key(item: ZoteroItem) -> str:
    last = item.creators[0].split()[-1] if item.creators else "anon"
    last = re.sub(r"[^a-zA-Z0-9]", "", last).lower() or "anon"
    year = item.year or "oJ"
    plain_title = re.sub(r"<[^>]+>", "", item.title)
    first_word = re.sub(r"[^a-zA-Z0-9]", "", (plain_title.split()[:1] or [""])[0]).lower()
    return f"{last}{year}{first_word}"


def item_to_bibtex(item: ZoteroItem) -> str:
    entry_type = _TYPE_MAP.get(item.item_type, "misc")
    fields = {
        "title": _rich_text_to_latex(item.title),
        "author": " and ".join(item.creators),
        "year": str(item.year) if item.year else "",
        "doi": item.doi,
    }
    if item.publication:
        key = "journal" if entry_type == "article" else "booktitle"
        fields[key] = item.publication
    if item.volume:
        fields["volume"] = item.volume
    if item.issue:
        fields["number"] = item.issue
    if item.pages:
        fields["pages"] = item.pages

    lines = [f"@{entry_type}{{{_cite_key(item)},"]
    for name, value in fields.items():
        if value:
            lines.append(f"  {name} = {{{_escape(value)}}},")
    lines.append("}")
    return "\n".join(lines)


def items_to_bibtex(items: list[ZoteroItem]) -> str:
    seen_keys: set[str] = set()
    entries = []
    for item in items:
        entry = item_to_bibtex(item)
        # disambiguate duplicate cite keys with a/b/c suffixes
        base_key = _cite_key(item)
        key = base_key
        suffix = "a"
        while key in seen_keys:
            key = base_key + suffix
            suffix = chr(ord(suffix) + 1)
        if key != base_key:
            entry = entry.replace(f"{{{base_key},", f"{{{key},", 1)
        seen_keys.add(key)
        entries.append(entry)
    return "\n\n".join(entries) + "\n"
