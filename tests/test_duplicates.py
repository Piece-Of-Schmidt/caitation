from backend.duplicates import dedupe_results, find_duplicate_groups, normalize_title


def test_normalize_title_ignores_case_punctuation_and_boilerplate():
    assert normalize_title("Original Article: The Euro-Crisis!") == normalize_title("the euro crisis")


def test_web_page_titles_lose_the_site_name():
    article = normalize_title("Narratives about the Macroeconomy")
    assert normalize_title("Narratives about the Macroeconomy | Publications | CESifo") == article
    assert normalize_title("Short | Site name that is long") != normalize_title("Short")  # head too short


def test_groups_merge_doi_and_title_matches(make_item):
    items = {
        "A": make_item(key="A", title="Monetary policy in the media", doi="10.1/x"),
        "B": make_item(key="B", title="Something else entirely here", doi="10.1/X"),
        "C": make_item(key="C", title="Monetary Policy in the Media"),
        "D": make_item(key="D", title="An unrelated paper title"),
    }
    groups = find_duplicate_groups(items)
    assert len(groups) == 1
    assert {i["item_key"] for i in groups[0]["items"]} == {"A", "B", "C"}


def test_dedupe_results_keeps_best_ranked_copy():
    results = [
        {"item_key": "A", "title": "Monetary policy in the media"},
        {"item_key": "B", "title": "Other paper with a long title"},
        {"item_key": "C", "title": "Monetary Policy in the Media"},
    ]
    deduped = dedupe_results(results)
    assert [r["item_key"] for r in deduped] == ["A", "B"]
    assert deduped[0]["duplicate_count"] == 1
