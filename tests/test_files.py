"""Local file connector: JSON, JSONL, Discourse topic JSON, raw exports and Markdown."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from decrack.sources.files import load_file

FIXTURES = Path(__file__).parent / "fixtures"


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


def source_of(path: Path) -> str:
    """``file:{sha8}``: the first 8 hex digits of the sha256 of the file's bytes."""
    return "file:" + hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def test_json_list_with_aliases_sorted_by_time():
    path = FIXTURES / "file_posts.json"
    thread = load_file(path)
    source = source_of(path)

    assert thread.id == "file:file_posts"
    assert thread.kind == "file"
    assert thread.title == "file_posts"
    assert thread.url == ""
    # carol's blank post is dropped; the rest are ordered by time, not by file position.
    assert [post.author for post in thread.posts] == ["alice", "bob", "dave"]
    assert [post.seq for post in thread.posts] == [1, 2, 3]
    # Ids keep the position in the file (bob comes first there), not the place in time order.
    assert [post.source_post_number for post in thread.posts] == [2, 1, 3]
    assert [post.id for post in thread.posts] == [f"{source}:2", f"{source}:1", f"{source}:3"]
    assert all(post.source_id == source and post.version == 1 for post in thread.posts)
    assert all(post.reply_to is None and post.quotes == [] for post in thread.posts)
    assert [post.created_at for post in thread.posts] == [utc(2025, 3, 1, 8, 0), utc(2025, 3, 2, 9, 0), utc(2025, 3, 3, 12, 30)]
    assert thread.posts[0].text == "Should we move the config file from INI to TOML? Nested settings are awkward in INI."
    assert thread.posts[0].sentences == ["Should we move the config file from INI to TOML?", "Nested settings are awkward in INI."]
    assert [(span.index, span.start, span.end) for span in thread.posts[0].spans] == [(1, 0, 48), (2, 49, 84)]
    assert "standard library" in thread.posts[2].text
    assert "<p>" not in thread.posts[2].text
    assert all(post.sentences and post.sha256 for post in thread.posts)
    assert all(post.role == "unknown" and post.url == "" for post in thread.posts)
    assert thread.meta == {"created_by": ["alice"], "path": "file_posts.json"}


def test_json_object_with_title_roles_and_created_by():
    path = FIXTURES / "file_thread.json"
    thread = load_file(path)

    assert thread.id == "file:file_thread"
    assert thread.title == "Pick a default line length"
    assert thread.url == "https://example.org/threads/line-length"
    assert [post.author for post in thread.posts] == ["frank", "erin", "grace", "heidi", "unknown"]
    # Without timestamps the file order is the thread order.
    assert [post.seq for post in thread.posts] == [1, 2, 3, 4, 5]
    assert [post.source_post_number for post in thread.posts] == [1, 2, 3, 4, 5]
    assert thread.posts[4].id == f"{source_of(path)}:5"
    # Valid roles are kept (case-insensitively); "chair" and a missing role become "unknown".
    assert [post.role for post in thread.posts] == ["participant", "author", "unknown", "decider", "unknown"]
    assert [post.url for post in thread.posts] == ["", "https://example.org/threads/line-length#2", "", "", ""]
    assert all(post.created_at is None for post in thread.posts)
    # The top-level created_by wins over the writer of post 1.
    assert thread.meta["created_by"] == ["erin"]
    assert thread.meta["path"] == "file_thread.json"


def test_jsonl_skips_blank_lines():
    path = FIXTURES / "file_chat.jsonl"
    thread = load_file(path)
    source = source_of(path)

    assert thread.id == "file:file_chat"
    assert [post.author for post in thread.posts] == ["henry", "ivy", "jack"]
    assert [post.id for post in thread.posts] == [f"{source}:1", f"{source}:2", f"{source}:3"]
    assert [post.text for post in thread.posts] == [
        "Can we drop support for 3.9 in the next release?",
        "Yes. Version 3.9 reaches end of life in October.",
        "Agreed, we will drop it.",
    ]
    assert thread.posts[2].created_at == utc(2025, 5, 1, 12, 0)  # an epoch-seconds timestamp
    assert thread.meta["created_by"] == ["henry"]


def test_discourse_topic_json_goes_through_topic_to_thread():
    thread = load_file(FIXTURES / "file_discourse_topic.json")

    assert thread.kind == "discourse"
    assert thread.id == "dpo:t4242"
    # A saved Discourse topic keeps the ids its posts have on the forum.
    assert [post.id for post in thread.posts] == ["dpo:4242:90001", "dpo:4242:90002"]
    assert [post.source_post_number for post in thread.posts] == [1, 2]
    assert [post.seq for post in thread.posts] == [1, 2]
    assert all(post.source_id == "dpo:t4242" for post in thread.posts)


def test_discourse_raw_export():
    path = FIXTURES / "file_raw_export.txt"
    thread = load_file(path)
    source = source_of(path)

    assert thread.id == "file:file_raw_export"
    assert thread.title == "file_raw_export"
    assert [post.author for post in thread.posts] == ["alice", "bob", "carol"]
    assert [post.id for post in thread.posts] == [f"{source}:1", f"{source}:2", f"{source}:3"]
    assert [post.created_at for post in thread.posts] == [
        utc(2025, 1, 5, 10, 0),
        utc(2025, 1, 5, 11, 30),
        utc(2025, 1, 6, 9, 15),
    ]
    assert thread.posts[0].text == (
        "I propose adding a --json flag to the report command. Scripts could then parse the output."
    )
    # The quote of alice's post is not bob's own words.
    assert thread.posts[1].text == "A separate export subcommand would be cleaner than a flag."
    assert not any("---" in post.text or "|" in post.text for post in thread.posts)
    assert thread.meta["created_by"] == ["alice"]


def test_markdown_with_separators_and_author_lines():
    path = FIXTURES / "file_notes.md"
    thread = load_file(str(path))
    source = source_of(path)

    assert thread.id == "file:file_notes"
    assert thread.title == "Choosing a cache backend"
    assert [post.author for post in thread.posts] == ["alice", "bob", "carol", "unknown"]
    assert [post.seq for post in thread.posts] == [1, 2, 3, 4]
    assert [post.id for post in thread.posts] == [f"{source}:{n}" for n in (1, 2, 3, 4)]
    assert thread.posts[0].text == "We need a cache for the API responses. I suggest Redis."
    bob = thread.posts[1].text
    assert bob.startswith("Redis adds a server to run.")
    # The "---" inside the fenced block does not split bob's post.
    assert "cache: memory\n---\ncache: redis" in bob
    assert bob.endswith("```")
    assert thread.posts[2].text == "Simpler is better here. We will use the in-process cache and revisit Redis later."
    assert thread.posts[3].text == "This post has no author line, so its author is unknown."
    assert not any("Choosing a cache backend" in post.text for post in thread.posts)
    assert all(post.created_at is None for post in thread.posts)
    assert thread.meta == {"created_by": ["alice"], "path": "file_notes.md"}


def test_plain_text_is_one_post():
    path = FIXTURES / "file_plain.txt"
    thread = load_file(path)

    assert thread.id == "file:file_plain"
    # "# set the cache size" sits in a code block, so it is not a title.
    assert thread.title == "file_plain"
    assert len(thread.posts) == 1
    post = thread.posts[0]
    assert post.author == "unknown"
    assert post.id == f"{source_of(path)}:1"
    assert post.source_post_number == 1 and post.seq == 1
    assert post.text.startswith("We could read the settings from environment variables")
    assert "# set the cache size" in post.text
    assert post.text.endswith("harder to discover.")
    assert post.sentences
    assert [post.text[span.start : span.end] for span in post.spans] == post.sentences
    assert thread.meta["created_by"] == []


def test_ids_pin_the_file_bytes(tmp_path):
    first = tmp_path / "a.md"
    first.write_text("alice:\nWe should cache it.\n", encoding="utf-8")
    copy = tmp_path / "b.md"
    copy.write_bytes(first.read_bytes())
    # The same bytes give the same post ids; the thread id still follows the file name.
    assert load_file(first).posts[0].id == load_file(copy).posts[0].id == f"{source_of(copy)}:1"
    assert (load_file(first).id, load_file(copy).id) == ("file:a", "file:b")

    first.write_text("alice:\nWe should cache it!\n", encoding="utf-8")
    edited = load_file(first)
    assert edited.posts[0].id == f"{source_of(first)}:1"
    assert edited.posts[0].id != load_file(copy).posts[0].id  # an edit never reuses the old ids


def test_windows_line_ends_read_like_unix_ones(tmp_path):
    unix = tmp_path / "unix.md"
    unix.write_bytes(b"alice:\nWe should cache it.\n\n---\n\nbob:\nNo caching.\n")
    windows = tmp_path / "windows.md"
    windows.write_bytes(b"alice:\r\nWe should cache it.\r\n\r\n---\r\n\r\nbob:\r\nNo caching.\r\n")
    expected = [("alice", "We should cache it."), ("bob", "No caching.")]
    assert [(post.author, post.text) for post in load_file(unix).posts] == expected
    assert [(post.author, post.text) for post in load_file(windows).posts] == expected


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_file(tmp_path / "missing.md")


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("number.json", "42"),
        ("no_posts.json", '{"title": "Nothing here"}'),
        ("broken.jsonl", '{"author": "kim", "text": "fine"}\n{not json\n'),
        ("empty.md", "# Only a title\n\n---\n"),
    ],
)
def test_unsupported_content(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_file(path)
