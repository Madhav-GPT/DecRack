"""Tests for decrack.text: NFC text, sentence spans and the invariants every citation relies on."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

import pytest

from decrack.models import Post, Thread
from decrack.text import (
    estimate_tokens,
    finalize_post,
    finalize_thread,
    nfc,
    normalize_ws,
    parse_time,
    quote_range,
    sentence_spans,
    sha256_text,
    slugify,
    split_sentences,
)

UTC = timezone.utc
LQ, RQ = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"
NFD_CAFE = "Cafe\N{COMBINING ACUTE ACCENT}"  # "e" followed by a combining accent (NFD)
NFC_CAFE = "Caf\N{LATIN SMALL LETTER E WITH ACUTE}"  # the same word with one precomposed letter (NFC)

SAMPLES = [
    "Plain sentence one. Plain sentence two! Is this three? Yes.",
    "We use e.g. decorators, i.e. functions. Version 3.12 shipped. See https://example.org/a.b. Then stop.",
    "Intro line.\n\n```python\ndef f():\n    return 1. \n```\n\nAfter code. Done.",
    "- first item. still first\n  wrapped line\n- second item\n\n1. numbered one\n2) numbered two",
    "# Heading\nText under heading. More text.",
    "Mr. Smith met Dr. Jones. They talked.",
    "Line one without stop\nline two continues. Next Sentence here.",
    'He said "stop." Then left. (Really.) Yes.',
    f"He said {LQ}Stop.{RQ} Then left.",
    f"{NFC_CAFE} au lait is served. {NFD_CAFE} noir too.",
    "Unclosed fence below.\n```\ncode without end. Still code.",
    "",
    "   \n\n  ",
]


def without_ws(text: str) -> str:
    return re.sub(r"\s+", "", text)


def make_post(text: str) -> Post:
    return finalize_post(Post(id="file:1a2b3c4d:1", seq=1, author="a", text=text))


@pytest.mark.parametrize("text", SAMPLES)
def test_sentences_cover_the_text_in_order(text):
    sentences = split_sentences(text)
    cursor = 0
    for sentence in sentences:
        assert sentence and sentence == sentence.strip()
        at = text.find(sentence, cursor)
        assert at >= 0, sentence
        assert text[cursor:at].strip() == ""  # only whitespace between sentences
        cursor = at + len(sentence)
    assert text[cursor:].strip() == ""
    assert without_ws("".join(sentences)) == without_ws(text)


@pytest.mark.parametrize("text", SAMPLES)
def test_spans_slice_the_nfc_text_into_its_sentences(text):
    post = make_post(text)
    assert post.text == nfc(text)
    assert [span.index for span in post.spans] == list(range(1, len(post.sentences) + 1))
    for span, sentence in zip(post.spans, post.sentences, strict=True):
        assert post.text[span.start : span.end] == sentence
    for before, after in zip(post.spans, post.spans[1:]):
        assert before.end <= after.start
        assert post.text[before.end : after.start].strip() == ""  # only whitespace between spans
    assert post.sentences == split_sentences(post.text)
    assert post.sha256 == hashlib.sha256(post.text.encode("utf-8")).hexdigest() == sha256_text(text)


def test_sentence_spans_are_offsets_into_the_text():
    assert sentence_spans("One here. Two here!") == [(0, 9), (10, 19)]
    text = "  Intro.\n\n```\ncode\n```\n"
    assert sentence_spans(text) == [(2, 8), (10, 22)]
    assert [text[start:end] for start, end in sentence_spans(text)] == ["Intro.", "```\ncode\n```"]
    assert sentence_spans("") == []
    assert sentence_spans(" \n ") == []


def test_joined_run_is_a_substring_after_normalising():
    text = "First point here.\nSecond point\nwraps here. Third point."
    sentences = split_sentences(text)
    assert normalize_ws(" ".join(sentences[0:2])) in normalize_ws(text)
    assert normalize_ws(" ".join(sentences[1:3])) in normalize_ws(text)


def test_basic_split():
    assert split_sentences("One here. Two here! Three here? four stays.") == [
        "One here.",
        "Two here!",
        "Three here? four stays.",
    ]


def test_abbreviations_and_decimals_do_not_split():
    text = "Use e.g. Decorators here. Python 3.12 is out. Ask Dr. Who today."
    assert split_sentences(text) == ["Use e.g. Decorators here.", "Python 3.12 is out.", "Ask Dr. Who today."]


def test_closing_quotes_and_brackets():
    assert split_sentences('He said "stop." Then left. (Really.) Yes.') == [
        'He said "stop."',
        "Then left.",
        "(Really.)",
        "Yes.",
    ]


def test_smart_quotes_end_and_start_sentences():
    assert split_sentences(f"He said {LQ}Stop.{RQ} Then left.") == [f"He said {LQ}Stop.{RQ}", "Then left."]
    assert split_sentences(f"It ended. {LQ}Why?{RQ} she asked.") == ["It ended.", f"{LQ}Why?{RQ} she asked."]


def test_code_block_is_one_unit():
    text = "Before the code.\n\n```python\nx = 1. \ny = 2\n```\n\nAfter it."
    assert split_sentences(text) == ["Before the code.", "```python\nx = 1. \ny = 2\n```", "After it."]


def test_list_items_stay_whole():
    text = "Options:\n- First idea. It wraps\n  onto two lines.\n- Second idea.\n1. Numbered. Item."
    assert split_sentences(text) == [
        "Options:",
        "- First idea. It wraps\n  onto two lines.",
        "- Second idea.",
        "1. Numbered. Item.",
    ]


def test_heading_is_one_unit():
    assert split_sentences("## Rejected Ideas\nWe dropped it. Fine.") == ["## Rejected Ideas", "We dropped it.", "Fine."]


def test_nfc_makes_both_spellings_one():
    assert NFD_CAFE != NFC_CAFE
    assert nfc(NFD_CAFE) == NFC_CAFE
    assert nfc(NFC_CAFE) == NFC_CAFE
    assert nfc("") == ""
    assert unicodedata.is_normalized("NFC", nfc(NFD_CAFE))
    assert sha256_text(NFD_CAFE) == sha256_text(NFC_CAFE) == hashlib.sha256(NFC_CAFE.encode("utf-8")).hexdigest()


def test_finalize_post_normalizes_before_splitting():
    post = make_post(f"{NFD_CAFE} is open. Tea too.")
    assert post.text == f"{NFC_CAFE} is open. Tea too."
    assert post.sentences == [f"{NFC_CAFE} is open.", "Tea too."]
    # Offsets count the precomposed letter once: they point into the stored NFC text.
    assert [(span.index, span.start, span.end) for span in post.spans] == [(1, 0, 13), (2, 14, 22)]
    assert post.sha256 == hashlib.sha256(post.text.encode("utf-8")).hexdigest()


def test_quote_range_cuts_one_contiguous_run():
    post = make_post("One here. Two here. Three here.")
    assert [(span.start, span.end) for span in post.spans] == [(0, 9), (10, 19), (20, 31)]
    assert quote_range(post, [2, 3]) == (10, 31, "Two here. Three here.")
    assert quote_range(post, [3, 2]) == (10, 31, "Two here. Three here.")  # the order of indexes does not matter
    assert quote_range(post, [1]) == (0, 9, "One here.")
    start, end, quote = quote_range(post, [1, 2, 3])
    assert quote == post.text[start:end] == post.text


@pytest.mark.parametrize("indexes", [[1, 3], [2, 2], []])
def test_quote_range_refuses_a_broken_run(indexes):
    with pytest.raises(ValueError, match="contiguous"):
        quote_range(make_post("One here. Two here. Three here."), indexes)


@pytest.mark.parametrize("indexes", [[0], [0, 1], [3, 4], [4]])
def test_quote_range_refuses_indexes_out_of_range(indexes):
    with pytest.raises(ValueError, match="out of range"):
        quote_range(make_post("One here. Two here. Three here."), indexes)


def test_parse_time_forms():
    expected = datetime(2025, 1, 5, 10, 0, tzinfo=UTC)
    assert parse_time("2025-01-05T10:00:00Z") == expected
    assert parse_time("2025-01-05T12:00:00+02:00") == expected
    assert parse_time("2025-01-05 10:00:00 UTC") == expected
    assert parse_time("Sun, 05 Jan 2025 10:00:00 +0000") == expected
    assert parse_time(1736071200) == expected
    assert parse_time(1736071200000) == expected
    assert parse_time("1736071200") == expected
    assert parse_time(datetime(2025, 1, 5, 10, 0)) == expected
    assert parse_time("2025-01-05T10:00:00.123Z").microsecond == 123000
    assert parse_time(0) == datetime(1970, 1, 1, tzinfo=UTC)
    assert parse_time("2025-01-05T12:00:00+02:00").tzinfo == UTC
    for bad in (None, "", "not a date", True, [2025]):
        assert parse_time(bad) is None


def test_hash_tokens_and_whitespace():
    assert sha256_text("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert normalize_ws("  a\n\tb   c ") == "a b c"
    assert estimate_tokens("abcd" * 10) == 11


def test_slugify():
    assert slugify("PEP 830: Timestamps in tracebacks!") == "pep-830-timestamps-in-tracebacks"
    assert slugify("Café déjà vu") == "cafe-deja-vu"
    assert slugify("") == "untitled"
    cut = slugify("word " * 30, max_len=20)
    assert cut == "word-word-word-word"


def test_finalize_thread_fills_sentences_spans_and_hash():
    thread = Thread(id="file:x", kind="file", posts=[Post(id="file:1a2b3c4d:1", seq=1, author="a", text="One. Two.")])
    assert finalize_thread(thread) is thread
    post = thread.posts[0]
    assert post.sentences == ["One.", "Two."]
    assert [(span.index, span.start, span.end) for span in post.spans] == [(1, 0, 4), (2, 5, 9)]
    assert post.sha256 == sha256_text("One. Two.")
    # Finalizing again (connectors and sources.load both do) changes nothing.
    before = post.model_dump()
    finalize_thread(thread)
    assert thread.posts[0].model_dump() == before
