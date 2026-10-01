"""Cleans text from PDF text layers. Shared by the indexer (new chunks), the search side
(snippets of chunks indexed before this cleaning existed) and the quote check."""

import re

# A word broken across lines: soft hyphen, or pdfium's U+FFFE marker for a hyphen it
# removed at a line end ("Flem￾ish"). Drop it plus any line break that follows.
_BROKEN_WORD = re.compile(r"[­￾]\s*")
# C0/C1 control codes (except tab and line break) and noncharacters: never text
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f￿]")


def clean_text(text: str) -> str:
    return CONTROL_CHARS.sub("", _BROKEN_WORD.sub("", text))


def looks_garbled(raw: str) -> bool:
    """True for a text layer without a usable character mapping: fonts that store glyph
    numbers instead of letters come out as control codes ("\\x92\\x83\\x92\\x87\\x94" for
    "paper"). Such pages are unreadable for search and need OCR like a scan."""
    visible = sum(1 for c in raw if not c.isspace())
    if visible < 50:
        return False
    return len(CONTROL_CHARS.findall(raw)) / visible > 0.2
