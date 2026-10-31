"""Tests for the Discourse connector, the pep:N resolver (with its leak guard) and the dispatcher.

HTTP goes through httpx.MockTransport serving saved JSON payloads from
tests/fixtures, so no test touches the network.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from decrack.config import Settings
from decrack.models import Thread
from decrack.sources import detect, load
from decrack.sources.discourse import cooked_to_text, load_topic, parse_topic_ref, topic_to_thread
from decrack.sources.peps import load_pep, looks_like_pep_text, topic_ids
from decrack.text import sha256_text

FIXTURES = Path(__file__).parent / "fixtures"
NFD_CAFE = "cafe\N{COMBINING ACUTE ACCENT}"  # "e" followed by a combining accent (NFD)
NFC_CAFE = "caf\N{LATIN SMALL LETTER E WITH ACUTE}"  # the same word with one precomposed letter (NFC)
POST_META_KEYS = {
    "topic_id",
    "post_number",
    "username",
    "name",
    "user_title",
    "flair_name",
    "primary_group_name",
    "moderator",
    "admin",
    "staff",
    "reply_to_post_number",
    "quote_refs",
}
PEP_META_KEYS = {"pep", "topic_ids", "created_by", "pep_authors", "forum", "posts_count", "leak_blanked"}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def mock_client(requests: list[httpx.Request] | None = None) -> httpx.Client:
    """A client that serves peps.json and the two fixture topics, and records each request."""
    routes = {
        "/api/peps.json": "peps_api.json",
        "/t/99001.json": "discourse_topic_99001.json",
        "/t/99002.json": "discourse_topic_99002.json",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        name = routes.get(request.url.path)
        if name is None:
            return httpx.Response(404, json={"errors": ["not found"]})
        return httpx.Response(200, json=fixture(name))

    return httpx.Client(transport=httpx.MockTransport(handler))


def assert_spans_match(thread: Thread) -> None:
    """Every post's spans slice its NFC text into exactly its sentences, numbered from 1."""
    for post in thread.posts:
        assert unicodedata.is_normalized("NFC", post.text)
        assert [span.index for span in post.spans] == list(range(1, len(post.sentences) + 1))
        assert [post.text[span.start : span.end] for span in post.spans] == post.sentences
        assert post.sha256 == sha256_text(post.text)


# Discourse ---------------------------------------------------------------------------


def test_cooked_to_text_drops_asides_and_keeps_code():
    html = fixture("discourse_topic_99001.json")["post_stream"]["posts"][1]["cooked"]
    text, quotes = cooked_to_text(html)
    assert quotes == [2]
    assert "Why not a decorator" not in text  # the quoted text is not the post's own
    assert text.startswith("A decorator cannot freeze instances. :slight_smile:")
    assert "```\n@frozen\nclass W: ...\n" in text


def test_onebox_preview_is_dropped():
    html = fixture("discourse_topic_99001.json")["post_stream"]["posts"][0]["cooked"]
    text, quotes = cooked_to_text(html)
    assert quotes == []
    assert "Abstract text copied" not in text
    assert text == (
        "This PEP proposes frozen widgets. Widgets would become immutable.\n\n## Motivation\n\nMutable widgets cause bugs."
    )


def test_topic_to_thread_orders_maps_and_fills_meta():
    thread = topic_to_thread(fixture("discourse_topic_99001.json"), "https://discuss.python.org")
    assert thread.id == "dpo:t99001"
    assert thread.kind == "discourse"
    assert thread.url == "https://discuss.python.org/t/pep-9001-frozen-widgets/99001"
    assert thread.title == "PEP 9001: Frozen widgets"
    assert thread.meta["created_by"] == ["alice"]
    assert thread.meta["topic_ids"] == [99001]
    # The JSON lists carol before bob; the thread is in time order. Ids are Discourse's own.
    assert [post.author for post in thread.posts] == ["alice", "bob", "carol", "sam"]
    assert [post.id for post in thread.posts] == [
        "dpo:99001:5001",
        "dpo:99001:5002",
        "dpo:99001:5003",
        "dpo:99001:5004",
    ]
    assert [post.seq for post in thread.posts] == [1, 2, 3, 4]
    assert [post.source_post_number for post in thread.posts] == [1, 2, 3, 4]
    assert all(post.source_id == "dpo:t99001" for post in thread.posts)
    assert all(post.role == "unknown" for post in thread.posts)

    alice, bob, carol, sam = thread.posts
    assert alice.sentences == [
        "This PEP proposes frozen widgets.",
        "Widgets would become immutable.",
        "## Motivation",
        "Mutable widgets cause bugs.",
    ]
    assert alice.reply_to is None and alice.quotes == []
    assert bob.sentences == ["Why not a decorator?", "It would avoid new `syntax`."]
    assert bob.reply_to == "dpo:99001:5001"
    assert carol.url == "https://discuss.python.org/t/pep-9001-frozen-widgets/99001/3"
    assert carol.reply_to == "dpo:99001:5002" and carol.quotes == ["dpo:99001:5002"]
    assert carol.sentences[0] == "A decorator cannot freeze instances. :slight_smile:"
    assert carol.sentences[1].startswith("```") and carol.sentences[1].endswith("```")
    assert set(carol.meta) == POST_META_KEYS
    assert carol.meta["topic_id"] == 99001
    assert carol.meta["post_number"] == 3 and carol.meta["reply_to_post_number"] == 2
    assert carol.meta["user_title"] == "CPython core developer"
    assert carol.meta["primary_group_name"] == "committers"
    assert carol.meta["quote_refs"] == [[99001, 2]]
    assert sam.meta["flair_name"] == "steering-council"
    assert sam.sentences == ["The Steering Council accepts PEP 9001.", "- Frozen by default.", "- No decorator."]
    assert carol.created_at == datetime(2026, 1, 10, 11, 0, tzinfo=timezone.utc)
    assert_spans_match(thread)


def test_discourse_version_is_captured():
    thread = topic_to_thread(fixture("discourse_topic_99001.json"))
    # carol's post was edited twice (version 3); bob's JSON has no version field, which means 1.
    assert [post.version for post in thread.posts] == [1, 1, 3, 1]


def test_nfd_text_is_stored_as_nfc():
    raw = fixture("discourse_topic_99002.json")
    assert NFD_CAFE in raw["post_stream"]["posts"][3]["cooked"]  # the fixture spells the word decomposed
    thread = topic_to_thread(raw)
    frank = thread.post_by_id("dpo:99002:6004")
    nfc_text = f"The {NFC_CAFE} example shows why. Frozen widgets are safer."
    assert frank.text == nfc_text
    assert NFD_CAFE not in frank.text
    assert frank.sentences == [f"The {NFC_CAFE} example shows why.", "Frozen widgets are safer."]
    assert frank.sha256 == sha256_text(nfc_text)
    assert frank.sha256 == hashlib.sha256(nfc_text.encode("utf-8")).hexdigest()  # the stored text is NFC
    assert_spans_match(thread)


def test_parse_topic_ref_forms():
    forum = "https://discuss.python.org"
    assert parse_topic_ref("https://discuss.python.org/t/pep-830-x/106942") == (forum, 106942)
    assert parse_topic_ref("https://discuss.python.org/t/pep-830-x/106942/17") == (forum, 106942)
    assert parse_topic_ref("https://discuss.python.org/t/106942/17") == (forum, 106942)
    assert parse_topic_ref("https://forum.example.org/t/topic/12?u=x") == ("https://forum.example.org", 12)
    assert parse_topic_ref(42) == (forum, 42)
    assert parse_topic_ref("42") == (forum, 42)
    with pytest.raises(ValueError):
        parse_topic_ref("https://discuss.python.org/c/ideas/6")


def test_load_topic_requests_print_true():
    requests: list[httpx.Request] = []
    thread = load_topic("https://discuss.python.org/t/pep-9001-frozen-widgets/99001/3", mock_client(requests))
    assert thread.id == "dpo:t99001"
    assert requests[0].url.params["print"] == "true"


def test_missing_topic_is_a_clear_error():
    with pytest.raises(ValueError, match="not found"):
        load_topic(12345, mock_client())


# pep:N -------------------------------------------------------------------------------


def test_topic_ids_from_peps_json():
    entry = fixture("peps_api.json")["9001"]
    assert topic_ids(entry) == [99001, 99002]  # post 5 of 99002 is not a topic; mail.python.org skipped
    assert topic_ids(fixture("peps_api.json")["9002"]) == []


def test_looks_like_pep_text():
    assert looks_like_pep_text("## Abstract\n\nText.\n\n## Specification\n\nMore.")
    assert looks_like_pep_text("Intro.\n\nRejected Ideas\n\nWe said no.")
    assert looks_like_pep_text("x" * 20001)
    assert not looks_like_pep_text("## Motivation\n\nOnly one section heading here.")
    assert not looks_like_pep_text("We discussed the motivation and the specification in detail.")


def test_load_pep_merges_topics_in_time_order():
    requests: list[httpx.Request] = []
    thread = load_pep(9001, mock_client(requests), leak_guard=False)
    assert thread.id == "pep:9001"
    assert thread.kind == "discourse"
    assert thread.title == "PEP 9001: Frozen widgets"  # the first topic's own title
    assert thread.url == "https://discuss.python.org/t/pep-9001-frozen-widgets/99001"
    assert set(thread.meta) == PEP_META_KEYS
    assert thread.meta["pep"] == 9001
    assert thread.meta["topic_ids"] == [99001, 99002]
    assert thread.meta["pep_authors"] == ["Alice Example", "Zed Other"]
    assert thread.meta["created_by"] == ["alice"]
    assert thread.meta["forum"] == "https://discuss.python.org"
    assert thread.meta["posts_count"] == 8
    assert thread.meta["leak_blanked"] == 0
    assert [post.id for post in thread.posts] == [
        "dpo:99001:5001",
        "dpo:99001:5002",
        "dpo:99002:6001",
        "dpo:99001:5003",
        "dpo:99001:5004",
        "dpo:99002:6002",
        "dpo:99002:6003",
        "dpo:99002:6004",
    ]
    assert [post.seq for post in thread.posts] == list(range(1, 9))
    assert [post.source_id for post in thread.posts] == [
        "dpo:t99001",
        "dpo:t99001",
        "dpo:t99002",
        "dpo:t99001",
        "dpo:t99001",
        "dpo:t99002",
        "dpo:t99002",
        "dpo:t99002",
    ]
    assert [post.source_post_number for post in thread.posts] == [1, 2, 1, 3, 4, 2, 3, 4]
    assert thread.post_by_id("dpo:99001:5003").version == 3  # the Discourse version survives the merge
    dave = thread.post_by_id("dpo:99002:6002")
    assert dave.sentences == ["I agree with carol."]
    assert_spans_match(thread)

    # peps.json only locates the topics: its title, status and resolution never enter the thread.
    dumped = json.dumps(thread.model_dump(mode="json"))
    assert "Immutable widget classes" not in dumped
    assert "Withdrawn" not in dumped
    assert "pep-9001-is-withdrawn" not in dumped
    assert [request.url.path for request in requests] == ["/api/peps.json", "/t/99001.json", "/t/99002.json"]


def test_same_post_number_in_two_topics_keeps_ids_and_edges_apart():
    thread = load_pep(9001, mock_client())
    ids = [post.id for post in thread.posts]
    assert len(set(ids)) == len(ids)
    assert [post.seq for post in thread.posts] == list(range(1, len(ids) + 1))

    # Post 2 of topic 99001 (bob) and post 2 of topic 99002 (dave) are different posts.
    bob = thread.post_by_id("dpo:99001:5002")
    dave = thread.post_by_id("dpo:99002:6002")
    assert bob.source_post_number == dave.source_post_number == 2
    assert (bob.seq, dave.seq) == (2, 6)

    carol = thread.post_by_id("dpo:99001:5003")
    assert carol.reply_to == bob.id and carol.quotes == [bob.id]  # "post 2" inside topic 99001
    frank = thread.post_by_id("dpo:99002:6004")
    assert frank.reply_to == dave.id and frank.quotes == [dave.id]  # "post 2" inside topic 99002
    assert dave.reply_to == "dpo:99002:6001"  # the round-two opener, not post 1 of topic 99001
    assert dave.quotes == [carol.id]  # a quote across topics
    assert thread.post_by_id("dpo:99001:5002").reply_to == "dpo:99001:5001"
    # No edge points at a position: every target is the id of a post in the thread.
    for post in thread.posts:
        assert all(thread.post_by_id(target) is not None for target in [post.reply_to, *post.quotes] if target)


def test_leak_guard_blanks_pasted_pep_text():
    thread = load_pep(9001, mock_client(), leak_guard=True)
    erin = thread.post_by_id("dpo:99002:6003")
    assert erin.seq == 7
    assert erin.text == "" and erin.sentences == [] and erin.spans == []
    assert erin.meta["leak_blanked"] is True
    assert erin.sha256 == sha256_text("")
    assert thread.meta["leak_blanked"] == 1
    assert thread.posts[0].sentences  # an opening post with one section heading stays
    assert thread.post_by_id("dpo:99002:6004").sentences  # a later reply stays too
    assert_spans_match(thread)


def test_unknown_pep_and_pep_without_topics():
    with pytest.raises(ValueError, match="not in"):
        load_pep(1, mock_client())
    with pytest.raises(ValueError, match="no discuss.python.org topic"):
        load_pep(9002, mock_client())


# Dispatcher -------------------------------------------------------------------------


def test_detect_forms(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Hello there.", encoding="utf-8")
    assert detect("pep:830") == "pep"
    assert detect("PEP 830") == "pep"
    assert detect("pep-0830") == "pep"
    assert detect("https://discuss.python.org/t/pep-830/106942") == "discourse"
    assert detect("https://github.com/python/cpython/issues/12345") == "github"
    assert detect("python/cpython#12345") == "github"
    assert detect(str(path)) == "file"


def test_existing_file_wins_over_the_github_short_form(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert detect("notes/chat#3") == "github"  # no such file: read as owner/repo#n
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "chat#3").write_text("alice:\nWe should cache it.\n", encoding="utf-8")
    assert detect("notes/chat#3") == "file"
    thread = load("notes/chat#3")
    assert thread.kind == "file"
    assert thread.id == "file:chat#3"
    assert [post.author for post in thread.posts] == ["alice"]
    assert thread.posts[0].sentences == ["We should cache it."]


@pytest.mark.parametrize(
    "ref",
    [
        "https://peps.python.org/pep-0830/",
        "https://github.com/python/peps/blob/main/peps/pep-0830.rst",
        "https://raw.githubusercontent.com/python/peps/main/peps/pep-0830.rst",
    ],
)
def test_pep_text_urls_are_refused(ref):
    with pytest.raises(ValueError, match="not PEP text"):
        detect(ref)


def test_unknown_and_missing_sources():
    with pytest.raises(FileNotFoundError):
        detect("missing-notes.json")
    with pytest.raises(ValueError, match="Unrecognized source"):
        detect("hello world")


def test_load_dispatches_with_leak_guard_from_settings():
    guarded = load("pep:9001", Settings(eval_mode=True), client=mock_client())
    assert guarded.meta["leak_blanked"] == 1
    plain = load("PEP 9001", Settings(), client=mock_client())
    assert plain.meta["leak_blanked"] == 0
    topic = load("https://discuss.python.org/t/pep-9001-frozen-widgets/99001", client=mock_client())
    assert topic.id == "dpo:t99001"
    assert all(post.role == "unknown" for post in topic.posts)  # roles come later, in compile


def test_load_reads_a_local_file(tmp_path):
    path = tmp_path / "decision.json"
    path.write_text(
        json.dumps([{"author": "alice", "text": "We should cache it."}, {"author": "bob", "text": "No caching."}]),
        encoding="utf-8",
    )
    sha8 = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    thread = load(str(path))
    assert thread.kind == "file"
    assert thread.id == "file:decision"
    assert [post.id for post in thread.posts] == [f"file:{sha8}:1", f"file:{sha8}:2"]
    assert [post.sentences for post in thread.posts] == [["We should cache it."], ["No caching."]]
