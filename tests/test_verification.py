import pytest

from backend import config
from backend.verification import extract_quotes, normalize, verify_quotes

SOURCE = (
    "since computers were able to execute part of their responsibilities by taking over "
    "routine tasks (Glahn 1970). Those advantages also seem to coincide with the increa-\n"
    "singly high market demands for fast and accurate news stories, making algorithmic "
    "news production even more beneﬁcial (Clerwall 2014; Diakopoulos 2019). Thanks to the above"
)
SOURCES = [{"item_key": "KOTENIDI", "title": "Algorithmic Journalism", "page": 4, "text": SOURCE}]


@pytest.fixture(autouse=True)
def no_keyword_index(tmp_path, monkeypatch):
    # isolate from the real index: step 2 (phrase search) finds nothing
    monkeypatch.setattr(config, "FTS_DB", tmp_path / "missing.sqlite")


def check(answer):
    return verify_quotes(answer, SOURCES)


def test_extracts_german_english_and_guillemet_quotes_but_not_short_terms():
    answer = ('Sie schreiben: „Those advantages also seem to coincide with demands" und '
              '"making algorithmic news production even more beneficial". Der „Hype" ist '
              'groß, »routine tasks are taken over by computers«.')
    assert extract_quotes(answer) == [
        "Those advantages also seem to coincide with demands",
        "making algorithmic news production even more beneficial",
        "routine tasks are taken over by computers",
    ]


def test_normalize_handles_ligatures_hyphenation_and_quotes():
    assert normalize("beneﬁcial") == normalize("beneficial")
    assert normalize("increa-\nsingly") == "increasingly"
    assert normalize("„A – B“") == normalize('"a - b"')


def test_exact_quote_with_primary_sources_is_verified():
    answer = ("„Those advantages also seem to coincide with the increasingly high market demands "
              "for fast and accurate news stories, making algorithmic news production even more "
              "beneficial (Clerwall 2014; Diakopoulos 2019)“ (Kotenidis & Veglis, 2021, S. 4).")
    [result] = check(answer)
    assert result["status"] == "verified"
    assert (result["item_key"], result["page"]) == ("KOTENIDI", 4)


def test_quote_with_omission_marks_is_verified_per_fragment():
    answer = "„Those advantages also seem to coincide […] making algorithmic news production even more beneficial“"
    assert check(answer)[0]["status"] == "verified"


def test_slightly_altered_quote_deviates():
    answer = "„Those advantages seem to coincide with the very high market demands for fast news stories“"
    assert check(answer)[0]["status"] == "deviates"


def test_invented_quote_is_not_found():
    answer = "„Newsrooms that automate reporting always lose the trust of their audience completely“"
    [result] = check(answer)
    assert result["status"] == "not_found"
    assert result["item_key"] is None


def test_answers_without_quotes_yield_nothing():
    assert check("Die Quelle stützt die Behauptung (Kotenidis & Veglis, 2021, S. 4).") == []


def test_cited_page_is_compared_with_the_source_page():
    quote = "„Those advantages also seem to coincide with the increasingly high market demands“"
    correct, wrong = (check(f"{quote} (Kotenidis & Veglis, 2021, S. {p})")[0] for p in (4, 12))
    assert (correct["cited_page"], correct["page_mismatch"]) == (4, False)
    assert (wrong["cited_page"], wrong["page_mismatch"]) == (12, True)
    assert check(f"{quote} (Kotenidis & Veglis, 2021)")[0]["cited_page"] is None


def test_page_reference_of_the_next_quote_is_not_borrowed():
    answer = ("„Those advantages also seem to coincide with the increasingly high market demands“ und "
              "„making algorithmic news production even more beneficial“ (S. 9)")
    first, second = check(answer)
    assert first["cited_page"] is None
    assert second["cited_page"] == 9


def test_language_heuristic():
    from backend.verification import language

    assert language("Die Hauptlimitierung des Modells ist, dass es die Zeit nicht berücksichtigt") == "de"
    assert language("The main limitation of the model is that it does not consider time") == "en"
    assert language("LDA K Topics") is None


def test_german_rendering_of_english_source_is_flagged_as_translation():
    answer = "„Diese Vorteile scheinen mit den steigenden Anforderungen des Marktes an schnelle Nachrichten zusammenzufallen“"
    [result] = check(answer)
    assert result["status"] == "translated"
    assert result["item_key"] is None  # a translation is never treated as verified
