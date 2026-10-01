from backend.rag import _chunk_excerpt, _clip


def test_clip_rejoins_words_split_across_lines():
    assert _clip("verteuerten Risikoauf-\nschläge für", 100) == "verteuerten Risikoaufschläge für"


def test_clip_keeps_real_suspended_hyphens():
    assert _clip("Wirtschafts- und Sozialpolitik", 100) == "Wirtschafts- und Sozialpolitik"


def test_clip_removes_soft_hyphens_and_broken_glyphs():
    assert _clip("kom­ plexeren Zu\udc9dsammenhang", 100) == "komplexeren Zusammenhang"


def test_clip_shortens_at_word_boundary():
    clipped = _clip("eins zwei drei vier fünf", 12)
    assert clipped == "eins zwei …"


def test_excerpt_prefers_keyword_snippet():
    assert _chunk_excerpt({"text": "ignored", "display": "…match here"}) == "…match here"


def test_excerpt_starts_at_next_sentence_instead_of_mid_word():
    text = "nd hostility drawing on the crisis. The German media presented it as"
    assert _chunk_excerpt({"text": text}) == "…The German media presented it as"


def test_excerpt_keeps_text_that_already_starts_cleanly():
    assert _chunk_excerpt({"text": "Complete sentence."}) == "Complete sentence."


def test_excerpts_without_page_are_not_labelled_page_zero():
    from backend.rag import _excerpt_location

    assert _excerpt_location({"page": 4, "chunk_type": "pdf"}) == "Seite 4"
    assert "Seite" not in _excerpt_location({"page": 0, "chunk_type": "metadata"})
    assert "Seite" not in _excerpt_location({"page": 0, "chunk_type": "document"})
