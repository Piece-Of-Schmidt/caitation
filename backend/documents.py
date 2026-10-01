"""Plain text from non-PDF attachments: saved web pages (HTML snapshots), EPUBs and text
files. Standard library only."""

import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

# page chrome that is rarely part of the actual article
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "nav", "header", "footer",
              "aside", "form", "button", "select"}
# where pages put their actual content; preferred over the whole page when substantial
_CONTENT_TAGS = {"main", "article"}
_MIN_CONTENT_CHARS = 500
_BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "ul", "ol", "br", "tr",
               "table", "blockquote", "pre", "figcaption", "dd", "dt",
               "h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []  # whole page
        self.content_parts: list[str] = []  # inside <main>/<article> only
        self.skip_depth = 0
        self.content_depth = 0

    def _emit(self, text):
        self.parts.append(text)
        if self.content_depth:
            self.content_parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in _CONTENT_TAGS:
            self.content_depth += 1
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._emit("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:  # <br/>, never opens a skipped region
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._emit("\n")
        if tag in _CONTENT_TAGS:
            self.content_depth = max(0, self.content_depth - 1)

    def handle_data(self, data):
        if not self.skip_depth:
            # line breaks in HTML source are just whitespace; real breaks come from tags
            self._emit(re.sub(r"\s+", " ", data))


def _clean(parts: list[str]) -> str:
    lines = (re.sub(r"\s+", " ", line).strip() for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    content = _clean(parser.content_parts)
    return content if len(content) >= _MIN_CONTENT_CHARS else _clean(parser.parts)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _epub_sections(path: Path) -> list[str]:
    """Text of each spine document (chapter) in reading order."""
    with zipfile.ZipFile(path) as epub:
        container = ElementTree.fromstring(epub.read("META-INF/container.xml"))
        opf_path = container.find(".//{*}rootfile").get("full-path")
        opf = ElementTree.fromstring(epub.read(opf_path))
        base = posixpath.dirname(opf_path)
        manifest = {item.get("id"): item.get("href") for item in opf.iterfind(".//{*}manifest/{*}item")}
        sections = []
        for ref in opf.iterfind(".//{*}spine/{*}itemref"):
            href = manifest.get(ref.get("idref"))
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(base, unquote(href)))
            try:
                text = html_to_text(_decode(epub.read(name)))
            except KeyError:
                continue
            if text:
                sections.append(text)
        return sections


def extract_sections(path: Path) -> list[str]:
    """Text of a document attachment, split into sections (EPUB chapters; a single
    section otherwise). Unreadable files yield an empty list."""
    try:
        suffix = path.suffix.lower()
        if suffix == ".epub":
            return _epub_sections(path)
        text = _decode(path.read_bytes())
        if suffix in (".html", ".htm", ".xhtml") or text.lstrip()[:1] == "<":
            text = html_to_text(text)
        return [text] if text.strip() else []
    except Exception:
        return []
