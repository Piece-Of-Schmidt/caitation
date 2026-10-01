"""Finds likely duplicate items in the Zotero library, matched by identical DOI
or normalized title. Groups are reported for manual merging in Zotero."""

import re

from backend.zotero_reader import ZoteroItem

# boilerplate prefixes that some translators prepend to otherwise identical titles
_TITLE_PREFIXES = re.compile(r"^(full article|original article|research article)\s*[:\-]?\s*", re.IGNORECASE)


def normalize_title(title: str) -> str:
    title = _TITLE_PREFIXES.sub("", title.strip())
    title = re.sub(r"[^a-z0-9äöüß ]", " ", title.lower())
    return re.sub(r"\s+", " ", title).strip()


def find_duplicate_groups(items: dict[str, ZoteroItem]) -> list[dict]:
    by_key: dict[str, list[ZoteroItem]] = {}
    reasons: dict[str, str] = {}

    for item in items.values():
        if item.doi:
            key = "doi:" + item.doi.strip().lower()
            by_key.setdefault(key, []).append(item)
            reasons[key] = "gleiche DOI"
        norm = normalize_title(item.title)
        if len(norm) >= 15:
            key = "title:" + norm
            by_key.setdefault(key, []).append(item)
            reasons[key] = "gleicher Titel"

    # merge overlapping groups (e.g. matched via DOI *and* title)
    groups: list[dict] = []
    assigned: dict[str, int] = {}  # item key -> group index
    for key, members in by_key.items():
        if len(members) < 2:
            continue
        target = None
        for item in members:
            if item.key in assigned:
                target = groups[assigned[item.key]]
                break
        if target is None:
            target = {"reason": reasons[key], "items": []}
            groups.append(target)
        for item in members:
            if item.key not in {i.key for i in target["items"]}:
                target["items"].append(item)
            assigned[item.key] = groups.index(target)

    result = []
    for group in groups:
        result.append(
            {
                "reason": group["reason"],
                "items": [
                    {
                        "item_key": i.key,
                        "title": i.title,
                        "authors": i.authors_str,
                        "year": i.year,
                        "item_type": i.item_type,
                        "has_pdf": bool(i.pdf_paths),
                        "zotero_link": i.zotero_link,
                    }
                    for i in group["items"]
                ],
            }
        )
    result.sort(key=lambda g: (g["items"][0]["title"] or "").lower())
    return result


def dedupe_results(results: list[dict]) -> list[dict]:
    """Collapses search results that are duplicates of each other (same normalized
    title); the best-ranked one survives and remembers how many copies exist."""
    seen: dict[str, dict] = {}
    deduped = []
    for r in results:
        norm = normalize_title(r.get("title") or "")
        if len(norm) >= 15 and norm in seen:
            seen[norm]["duplicate_count"] = seen[norm].get("duplicate_count", 0) + 1
            continue
        if len(norm) >= 15:
            seen[norm] = r
        deduped.append(r)
    return deduped
