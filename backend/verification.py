"""Checks that verbatim quotes in Claude's answers really occur in the sources.

A fabricated or altered quote in a thesis is a serious problem for the user, so every
quote in an answer gets a status:

- "verified":   found word for word (ignoring case, whitespace, hyphenation, ligatures
                and quote/dash variants) in a source excerpt or in the keyword index
- "deviates":   a close but not exact match (e.g. a word changed or left out)
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


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)  # ligatures (ﬁ -> fi), full-width forms
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # hyphenation across lines
    text = re.sub(r"[‐‑‒–—―]", "-", text)
    text = re.sub(r"[„“”«»‚‘’\"']", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def extract_quotes(answer: str) -> list[str]:
    quotes = []
    for match in _QUOTE.finditer(answer):
        quote = next(group for group in match.groups() if group is not None).strip()
        if len(quote) >= MIN_QUOTE_CHARS and quote not in quotes:
            quotes.append(quote)
    return quotes


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
    for quote in extract_quotes(answer):
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

        results.append({
            "quote": quote,
            "status": status,
            "item_key": source.get("item_key") if source else None,
            "title": source.get("title", "") if source else "",
            "page": source.get("page") if source else None,
        })
    return results
