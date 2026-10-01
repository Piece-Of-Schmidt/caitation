"""Checks that verbatim quotes in Claude's answers really occur in the sources.

A fabricated or altered quote in a thesis is a serious problem for the user, so every
quote in an answer gets a status:

- "verified":   found word for word (ignoring case, whitespace, hyphenation, ligatures
                and quote/dash variants) in a source excerpt or in the keyword index
- "deviates":   a close but not exact match (e.g. a word changed or left out)
- "translated": not found, but the quote is German and the sources are English: most
                likely Claude's own translation in quotation marks. Not a usable quote,
                and deliberately not "verified": a translation can't be checked word for word.
- "not_found":  nothing similar in the sources
"""

import difflib
import re
import sqlite3
import unicodedata

from backend import config

# „…“ „…" “…” "…" »…« ‚…‘ (German, English and guillemet quotes)
_QUOTE = re.compile(r'„([^“”"\n]+)[“”"]|“([^”\n]+)”|"([^"\n]+)"|»([^«\n]+)«|‚([^‘’\n]+)[‘’]')
_ELLIPSIS = re.compile(r"\s*(?:\[\s*(?:\.\.\.|…)\s*\]|\.\.\.|…)\s*")
MIN_QUOTE_CHARS = 25  # shorter quoted strings are terms or titles, not citations
MIN_FRAGMENT_CHARS = 12
DEVIATION_THRESHOLD = 0.8


_STOPWORDS = {  # function words unique to one language ("in", "an" exist in both)
    "de": {"der", "die", "das", "und", "ist", "nicht", "mit", "von", "zu", "den", "dem", "des",
           "dass", "sich", "auf", "für", "eine", "ein", "einer", "werden", "wird", "auch", "bei",
           "oder", "wie", "zwischen", "sind", "im", "durch", "nach", "über", "diese", "dieser"},
    "en": {"the", "and", "is", "not", "with", "of", "to", "that", "for", "are", "be", "this",
           "by", "on", "or", "from", "between", "which", "it", "its", "was", "were", "has",
           "have", "their", "these", "than"},
}


def language(text: str) -> str | None:
    """'de' or 'en' by function words; None if unclear. Only needs to tell these two apart."""
    words = re.findall(r"[a-zäöüß]+", text.casefold())
    scores = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    other = min(scores, key=scores.get)
    return best if scores[best] >= 2 and scores[best] > 2 * scores[other] else None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)  # ligatures (ﬁ -> fi), full-width forms
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # hyphenation across lines
    text = re.sub(r"[‐‑‒–—―]", "-", text)
    text = re.sub(r"[„“”«»‚‘’\"']", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


# page reference right after a quote: "(Kotenidis & Veglis, 2021, S. 4)", "(p. 12)"
_PAGE_REF = re.compile(r"\b(?:S\.|Seite|pp?\.)\s*(\d+)")
_PAGE_REF_WINDOW = 80


def _quotes_with_cited_pages(answer: str) -> list[tuple[str, int | None]]:
    quotes: dict[str, int | None] = {}
    for match in _QUOTE.finditer(answer):
        quote = next(group for group in match.groups() if group is not None).strip()
        if len(quote) < MIN_QUOTE_CHARS or quote in quotes:
            continue
        after = answer[match.end() : match.end() + _PAGE_REF_WINDOW].split("\n")[0]
        after = _QUOTE.split(after)[0]  # stop at the next quote
        page = _PAGE_REF.search(after)
        quotes[quote] = int(page.group(1)) if page else None
    return list(quotes.items())


def extract_quotes(answer: str) -> list[str]:
    return [quote for quote, _page in _quotes_with_cited_pages(answer)]


def _fragments(quote: str) -> list[str]:
    """Parts of a quote between omission marks ("…", "[...]"), each checked on its own."""
    parts = [p.strip(" ,;:") for p in _ELLIPSIS.split(quote)]
    return [p for p in parts if len(p) >= MIN_FRAGMENT_CHARS] or [quote]


def _coverage(fragment: str, text: str) -> float:
    """Share of the fragment found in the best-matching region of text, counting only
    contiguous runs of 4+ characters (so scattered single letters don't count).
    Altered quotes score ~0.9+, invented ones on the same topic ~0.1-0.35."""
    if not text or not fragment:
        return 0.0
    best = 0.0
    matcher = difflib.SequenceMatcher(None, text, fragment, autojunk=False)
    for block in matcher.get_matching_blocks():
        if block.size < 8:
            continue
        start = max(0, block.a - block.b - 10)
        window = text[start : start + int(len(fragment) * 1.4) + 20]  # room for omitted words
        local = difflib.SequenceMatcher(None, window, fragment, autojunk=False)
        matched = sum(b.size for b in local.get_matching_blocks() if b.size >= 4)
        best = max(best, matched / len(fragment))
    return best


def _fts_phrase_hit(fragment: str) -> tuple[str, int] | None:
    """(item_key, page) of a chunk containing the fragment as a phrase, via the keyword index."""
    tokens = re.findall(r"\w+", fragment)
    if len(tokens) < 3 or not config.FTS_DB.exists():
        return None
    phrase = '"' + " ".join(tokens) + '"'
    con = sqlite3.connect(f"file:{config.FTS_DB}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select item_key, page from chunks where chunks match ? limit 1", (phrase,)
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        con.close()
    return (row[0], int(row[1] or 0)) if row else None


def verify_quotes(answer: str, sources: list[dict]) -> list[dict]:
    """sources: [{"item_key", "title", "page", "text"}] — the excerpts given to Claude."""
    prepared = [(s, normalize(s.get("text", ""))) for s in sources]
    titles = {s["item_key"]: s.get("title", "") for s in sources}
    results = []
    for quote, cited_page in _quotes_with_cited_pages(answer):
        fragments = [normalize(f) for f in _fragments(quote)]
        status, source, best = "not_found", None, 0.0

        # 1) word for word in an excerpt Claude was given
        for src, text in prepared:
            if all(f in text for f in fragments):
                status, source = "verified", src
                break

        # 2) word for word elsewhere in the library (e.g. just outside the excerpt)
        if status != "verified":
            hits = [_fts_phrase_hit(f) for f in _fragments(quote)]
            if all(hits):
                key, page = hits[0]
                status = "verified"
                source = {"item_key": key, "title": titles.get(key, ""), "page": page}

        # 3) close but altered
        if status != "verified":
            for src, text in prepared:
                ratio = min(_coverage(f, text) for f in fragments)
                if ratio > best:
                    best, source = ratio, src
            status = "deviates" if best >= DEVIATION_THRESHOLD else "not_found"
            if status == "not_found":
                source = None
                source_languages = {language(src.get("text", "")) for src in sources} - {None}
                if language(quote) == "de" and source_languages == {"en"}:
                    status = "translated"

        found_page = source.get("page") if source else None
        results.append({
            "quote": quote,
            "status": status,
            "item_key": source.get("item_key") if source else None,
            "title": source.get("title", "") if source else "",
            "page": found_page,
            "cited_page": cited_page,
            # an excerpt starts on found_page and may run onto the next page
            "page_mismatch": bool(
                cited_page and found_page and status != "not_found"
                and cited_page not in (found_page, found_page + 1)
            ),
        })
    return results
