"""GitHub connector: reference forms, issue and PR threads, headers and errors.

Every request goes to an ``httpx.MockTransport`` that answers from a fixture
mapping API paths (plus ``?page=N`` for later pages) to JSON bodies.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from decrack.sources.github import GITHUB_API, is_github_ref, load_github, parse_github_ref, pr_summary

FIXTURES = Path(__file__).parent / "fixtures"


def routes(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def mock_client(table: dict, seen: list[httpx.Request] | None = None) -> httpx.Client:
    """A client answering from ``table``; a page with a successor gets a ``Link: rel="next"`` header."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        path = request.url.path
        page = int(request.url.params.get("page", "1"))
        key = path if page == 1 else f"{path}?page={page}"
        if key not in table:
            return httpx.Response(404, json={"message": "Not Found"})
        headers = {}
        if f"{path}?page={page + 1}" in table:
            headers["Link"] = f'<{GITHUB_API}{path}?per_page=100&page={page + 1}>; rel="next"'
        return httpx.Response(200, json=table[key], headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.mark.parametrize(
    "ref",
    [
        "https://github.com/octo/widgets/issues/7",
        "https://github.com/octo/widgets/pull/7",
        "https://github.com/octo/widgets/pull/7/files?diff=split#r123",
        "https://github.com/octo/widgets/issues/7#issuecomment-1001",
        "octo/widgets#7",
        "gh:octo/widgets#7",
        "  octo/widgets#7 ",
    ],
)
def test_parse_github_ref_forms(ref):
    assert parse_github_ref(ref) == ("octo", "widgets", 7)
    assert is_github_ref(ref)


@pytest.mark.parametrize(
    "ref",
    [
        "https://github.com/octo/widgets/commit/abc123",
        "https://discuss.python.org/t/some-topic/7",
        "octo/widgets",
        "octo/widgets#0",
        "notes.md",
    ],
)
def test_bad_ref(ref):
    with pytest.raises(ValueError):
        parse_github_ref(ref)
    assert not is_github_ref(ref)


def test_issue_thread():
    with mock_client(routes("github_issue.json")) as client:
        thread = load_github("https://github.com/octo/widgets/issues/7", client)

    assert thread.id == "gh:octo/widgets#7"
    assert thread.kind == "github_issue"
    assert thread.url == "https://github.com/octo/widgets/issues/7"
    assert thread.title == "Add a YAML loader for widget configs"
    assert [post.seq for post in thread.posts] == [1, 2, 3]
    assert [post.id for post in thread.posts] == [
        "gh:octo/widgets#7",
        "gh:octo/widgets#7:c1001",
        "gh:octo/widgets#7:c1002",
    ]
    # Every post belongs to the issue; GitHub has no per-thread post numbers or edit versions here.
    assert all(post.source_id == "gh:octo/widgets#7" for post in thread.posts)
    assert all(post.source_post_number is None for post in thread.posts)
    assert all(post.version == 1 for post in thread.posts)
    assert all(post.reply_to is None and post.quotes == [] for post in thread.posts)
    assert [post.author for post in thread.posts] == ["riley", "morgan", "ghost"]
    assert [post.meta["kind"] for post in thread.posts] == ["body", "comment", "comment"]
    assert [post.meta["author_association"] for post in thread.posts] == ["CONTRIBUTOR", "MEMBER", "NONE"]
    assert all(post.role == "unknown" for post in thread.posts)

    body = thread.posts[0]
    assert body.text == "Widget configs are JSON only. I propose a YAML loader so configs can have comments."
    assert body.created_at == datetime(2025, 2, 10, 9, 0, tzinfo=timezone.utc)
    assert body.url == "https://github.com/octo/widgets/issues/7"
    assert body.sentences == ["Widget configs are JSON only.", "I propose a YAML loader so configs can have comments."]
    assert [(span.index, span.start, span.end) for span in body.spans] == [(1, 0, 29), (2, 30, 83)]
    assert thread.posts[1].url == "https://github.com/octo/widgets/issues/7#issuecomment-1001"
    assert all(post.sentences and post.sha256 for post in thread.posts)
    for post in thread.posts:
        assert [post.text[span.start : span.end] for span in post.spans] == post.sentences

    meta = thread.meta
    assert meta["repo"] == "octo/widgets"
    assert meta["number"] == 7
    assert meta["state"] == "closed"
    assert meta["state_reason"] == "not_planned"
    assert meta["labels"] == ["enhancement", "wontfix"]
    assert meta["closed_by"] == "morgan"
    assert meta["opener"] == "riley"
    assert meta["merged"] is False
    assert meta["merged_at"] is None
    assert meta["merged_by"] is None
    assert meta["files"] == []
    assert meta["reviews"] == []


def test_pr_thread_with_reviews_and_paginated_comments():
    seen: list[httpx.Request] = []
    with mock_client(routes("github_pr.json"), seen) as client:
        thread = load_github("gh:octo/widgets#12", client)

    assert thread.id == "gh:octo/widgets#12"
    assert thread.kind == "github_pr"
    assert thread.url == "https://github.com/octo/widgets/pull/12"
    assert thread.title == "Fix crash when a widget list is empty"
    # The empty APPROVED review is not a post; the review and its comment tie on time and keep fetch order.
    assert [post.id.removeprefix("gh:octo/widgets#12") for post in thread.posts] == [
        "",
        ":c2001",
        ":r3001",
        ":rc4001",
        ":c2002",
        ":c2003",
    ]
    assert [post.seq for post in thread.posts] == [1, 2, 3, 4, 5, 6]
    assert all(post.source_id == "gh:octo/widgets#12" for post in thread.posts)
    assert all(post.source_post_number is None and post.version == 1 for post in thread.posts)
    assert [post.meta["kind"] for post in thread.posts] == [
        "body",
        "comment",
        "review",
        "review_comment",
        "comment",
        "comment",
    ]
    assert [post.author for post in thread.posts] == ["dana", "eli", "maya", "maya", "dana", "maya"]

    review, review_comment = thread.posts[2], thread.posts[3]
    assert review.text == "Please add a test for the empty case."
    assert review.meta["review_state"] == "CHANGES_REQUESTED"
    assert review.created_at == datetime(2025, 4, 1, 13, 0, tzinfo=timezone.utc)
    assert review_comment.meta["path"] == "src/widgets/render.py"
    assert review_comment.url == "https://github.com/octo/widgets/pull/12#discussion_r4001"
    assert all(post.sentences for post in thread.posts)

    meta = thread.meta
    assert meta["merged"] is True
    assert meta["merged_at"] == "2025-04-02T11:05:00Z"
    assert meta["merged_by"] == "maya"
    assert meta["closed_by"] == "maya"
    assert meta["state_reason"] is None
    assert meta["files"] == ["src/widgets/render.py", "tests/test_render.py"]
    assert meta["labels"] == ["bug"]
    assert meta["opener"] == "dana"
    assert meta["reviews"] == [
        {"user": "maya", "state": "CHANGES_REQUESTED", "author_association": "MEMBER"},
        {"user": "maya", "state": "APPROVED", "author_association": "MEMBER"},
    ]
    assert "e5bd3914" not in json.dumps(thread.model_dump(mode="json"))

    comment_pages = [r.url.params.get("page") for r in seen if r.url.path.endswith("/issues/12/comments")]
    assert comment_pages == [None, "2"]
    lists = [r for r in seen if r.url.path.endswith(("/comments", "/reviews", "/files"))]
    assert len(lists) == 5
    assert all(r.url.params.get("per_page") == "100" for r in lists)


def test_authorization_header_only_with_token(monkeypatch):
    table = routes("github_issue.json")
    seen: list[httpx.Request] = []
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-123")
    with mock_client(table, seen) as client:
        load_github("octo/widgets#7", client)
    assert len(seen) == 2
    assert all(r.headers.get("Authorization") == "Bearer test-token-123" for r in seen)
    assert all(r.headers["Accept"] == "application/vnd.github+json" for r in seen)
    assert all(r.headers["X-GitHub-Api-Version"] == "2022-11-28" for r in seen)

    seen.clear()
    monkeypatch.delenv("GITHUB_TOKEN")
    with mock_client(table, seen) as client:
        load_github("octo/widgets#7", client)
    assert len(seen) == 2
    assert all("Authorization" not in r.headers for r in seen)
    assert all(r.headers["Accept"] == "application/vnd.github+json" for r in seen)


def test_rate_limit_raises_runtime_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "API rate limit exceeded"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
            load_github("octo/widgets#7", client)


def test_missing_issue_names_the_ref():
    with mock_client({}) as client:
        with pytest.raises(ValueError, match="octo/widgets#99"):
            load_github("octo/widgets#99", client)


def test_pr_summary():
    with mock_client(routes("github_pr.json")) as client:
        summary = pr_summary("https://github.com/octo/widgets/pull/12", client)
    assert summary == {
        "owner": "octo",
        "repo": "widgets",
        "number": 12,
        "title": "Fix crash when a widget list is empty",
        "body": "Rendering an empty widget list raised IndexError. This change returns an empty frame instead.",
        "files": ["src/widgets/render.py", "tests/test_render.py"],
        "merged": True,
    }
