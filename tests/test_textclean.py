from backend.textclean import clean_text, looks_garbled


def test_words_broken_across_lines_are_rejoined():
    assert clean_text("Flem￾ish news") == "Flemish news"  # pdfium hyphen marker
    assert clean_text("en\xad\ncoded") == "encoded"  # soft hyphen + line break


def test_control_codes_are_dropped_but_line_breaks_kept():
    assert clean_text("a\x03b\x92c\nd\te") == "abc\nd\te"


def test_glyph_number_text_layer_is_detected():
    # "The paper also finds that ..." from a font without a character mapping
    garbled = "\x17\x8a\x87\x03 \x92\x83\x92\x87\x94\x03 \x83\x8e\x95\x91\x03 \x88\x8b\x90\x86\x95\x03 " * 5
    assert looks_garbled(garbled)
    assert not looks_garbled("Ordinary text with the odd \x03 control code in it. " * 3)
