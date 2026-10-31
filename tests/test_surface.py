"""check_change: related history found by path, PR number, description, PR URL and local diff (blame opt-in)."""

from __future__ import annotations

import shutil

import httpx
import pytest

from decrack import linking
from decrack.search import NOTICE
from decrack.surface import NO_MATCHES, POSSIBLE_CONFLICT, REPORT_TITLE, check_change, render_report

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

PULL = {
    "number": 42,
    "title": "Make widget loading lazy with a decorator",
    "body": "Adds a lazy decorator to the widget loader.",
    "state": "open",
    "merged": False,
    "merged_at": None,
    "merged_by": None,
    "draft": False,
    "user": {"login": "alice"},
    "author_association": "MEMBER",
    "html_url": "https://github.com/example/widgets/pull/42",
    "url": "https://api.github.com/repos/example/widgets/pulls/42",
    "created_at": "2026-01-09T10:00:00Z",
    "updated_at": "2026-01-10T10:00:00Z",
    "closed_at": None,
    "labels": [],
    "head": {"ref": "lazy-widgets", "sha": "c3" * 20},
    "base": {"ref": "main", "sha": "d4" * 20},
    "comments": 0,
    "review_comments": 0,
    "changed_files": 1,
}
ISSUE = {
    "number": 42,
    "title": PULL["title"],
    "body": PULL["body"],
    "state": "open",
    "state_reason": None,
    "user": {"login": "alice"},
    "author_association": "MEMBER",
    "html_url": PULL["html_url"],
    "created_at": PULL["created_at"],
    "updated_at": PULL["updated_at"],
    "closed_at": None,
    "closed_by": None,
    "labels": [],
    "comments": 0,
    "pull_request": {"html_url": PULL["html_url"], "merged_at": None},
}
FILES = [{"filename": "Lib/lazy.py", "status": "modified", "additions": 1, "deletions": 1, "changes": 2}]


def github_api(request: httpx.Request) -> httpx.Response:
    """Just enough of the GitHub REST API for PR 42; list endpoints it does not know are empty."""
    path = request.url.path
    if path.endswith("/pulls/42/files"):
        first_page = request.url.params.get("page", "1") == "1"
        return httpx.Response(200, json=FILES if first_page else [])
    if path.endswith("/pulls/42"):
        return httpx.Response(200, json=PULL)
    if path.endswith("/issues/42"):
        return httpx.Response(200, json=ISSUE)
    return httpx.Response(200, json=[])


@pytest.fixture
def saved(store, synthetic_thread, sample_record):
    store.save_thread(synthetic_thread)
    store.save_record(sample_record)
    return sample_record


def test_paths_find_linked_records(store, saved, synthetic_thread):
    post2, post5 = synthetic_thread.posts[1], synthetic_thread.posts[4]
    result = check_change(store, paths=["Lib/widgets.py"])
    assert result["paths"] == ["Lib/widgets.py"]
    assert result["prs"] == []
    [match] = result["matches"]
    assert match["record_id"] == saved.id
    assert match["question"] == "PEP 9999: Lazy widgets"
    assert match["thread_url"] == saved.thread_url
    # The thread names Lib/widgets.py itself, so the link is direct.
    assert match["why"] == ["file Lib/widgets.py (mentioned, direct)"]
    assert match["strength"] == "direct"
    # Rejected options first, then the accepted one; proposed or unresolved ones are left out.
    assert [option["key"] for option in match["options"]] == ["A1", "A2", "A4", "A3"]
    first = match["options"][0]
    assert (first["status"], first["status_kind"]) == ("rejected", "confirmed")
    assert first["reasons"] == ["Decorators cannot apply to import statements."]
    # A1 cites post 2 and post 5 (post 5 twice: as option and as reason evidence). Each quote is
    # listed once, and the quote from the post that set the status (post 5) comes first.
    assert [ev["post_id"] for ev in first["evidence"]] == [post5.id, post2.id]
    assert first["evidence"][0] == {
        "quote": "We rejected the decorator approach because decorators cannot apply to import statements.",
        "url": post5.url,
        "author": "alice",
        "post_id": post5.id,
    }

    markdown = result["markdown"]
    assert REPORT_TITLE in markdown
    assert NOTICE in markdown
    assert "**rejected** (confirmed): Use a decorator instead of a new keyword" in markdown
    assert f"([alice]({post5.url}))" in markdown
    assert POSSIBLE_CONFLICT in markdown
    assert NO_MATCHES not in markdown


def test_report_wording_is_history_not_a_verdict(store, saved):
    markdown = check_change(store, paths=["Lib/widgets.py", "Lib/lazy.py"], description="decorator")["markdown"]
    lowered = markdown.lower()
    assert "related history / possible conflict" in lowered
    assert "invalid" not in lowered
    assert "violat" not in lowered
    empty = check_change(store, paths=["Tools/unrelated/thing.py"])["markdown"].lower()
    assert "related history" in empty
    assert "invalid" not in empty and "violat" not in empty


def test_unsupported_quotes_and_reasons_are_left_out(store, saved, sample_record, synthetic_thread):
    post2, post5 = synthetic_thread.posts[1], synthetic_thread.posts[4]
    first = sample_record.options[0]
    unsupported = {"support": "unsupported"}
    reason = first.reasons[0].model_copy(
        update={**unsupported, "evidence": [ev.model_copy(update=unsupported) for ev in first.reasons[0].evidence]}
    )
    evidence = [ev.model_copy(update=unsupported) if ev.post_id == post5.id else ev for ev in first.evidence]
    changed = first.model_copy(update={"reasons": [reason], "evidence": evidence})
    store.save_record(sample_record.model_copy(update={"options": [changed, *sample_record.options[1:]]}))
    [match] = check_change(store, paths=["Lib/widgets.py"])["matches"]
    view = match["options"][0]
    assert view["key"] == "A1"
    assert view["reasons"] == []
    assert [ev["post_id"] for ev in view["evidence"]] == [post2.id]


@requires_git
def test_pr_numbers_from_a_local_diff(tmp_path, store, saved):
    """No path matches here: the record is found only when the opt-in blame leads to PR 42."""
    root = tmp_path / "clone"
    root.mkdir()

    def git(*args: str) -> str:
        return linking.git(root, *args)

    git("init", "-q")
    git("config", "user.name", "Test Author")
    git("config", "user.email", "author@example.com")
    git("config", "commit.gpgsign", "false")
    git("remote", "add", "origin", "https://github.com/example/widgets.git")
    (root / "Tools").mkdir()
    script = root / "Tools" / "build.py"
    script.write_text("STEPS = 1\nDEBUG = False\n", encoding="utf-8", newline="\n")
    git("add", "Tools/build.py")
    git("commit", "-q", "--no-verify", "-m", "Add the build script (#42)")
    base = git("rev-parse", "HEAD").strip()
    script.write_text("STEPS = 2\nDEBUG = False\n", encoding="utf-8", newline="\n")
    git("commit", "-q", "--no-verify", "-a", "-m", "Build in two steps")
    head = git("rev-parse", "HEAD").strip()

    # By default the diff brings only its changed paths: no blame, so no PR numbers.
    plain = check_change(store, diff=f"{base}..{head}", repo_dir=root)
    assert plain["paths"] == ["Tools/build.py"]
    assert plain["prs"] == []
    assert plain["matches"] == []

    result = check_change(store, diff=f"{base}..{head}", repo_dir=root, blame=True)
    assert result["paths"] == ["Tools/build.py"]
    assert result["prs"] == [42]
    [match] = result["matches"]
    assert match["record_id"] == saved.id
    assert match["why"] == ["PR #42"]
    # Found through the record's pr_files link to PR 42: a git fact, so historical.
    assert match["strength"] == "historical"
    assert "#42" in result["markdown"]


def test_description_finds_records_by_text(store, saved):
    result = check_change(store, description="Switch to a decorator")
    [match] = result["matches"]
    assert match["record_id"] == saved.id
    assert match["why"] == ["text match"]
    assert match["strength"] == "suggested"
    assert result["paths"] == [] and result["prs"] == []


def test_no_related_records(store, saved):
    result = check_change(store, paths=["Tools/unrelated/thing.py"])
    assert result["matches"] == []
    assert NO_MATCHES in result["markdown"]
    assert "`Tools/unrelated/thing.py`" in result["markdown"]


def test_pr_url_brings_files_number_and_text(store, saved):
    client = httpx.Client(transport=httpx.MockTransport(github_api))
    try:
        result = check_change(store, pr_url="https://github.com/example/widgets/pull/42", client=client)
    finally:
        client.close()
    assert "Lib/lazy.py" in result["paths"]
    assert result["prs"] == [42]
    [match] = result["matches"]
    assert match["record_id"] == saved.id
    # The strongest of its links counts: the PR's files and number (historical) beat the text match.
    assert match["strength"] == "historical"
    assert "file Lib/lazy.py (pr_files, historical)" in match["why"]
    assert "PR #42" in match["why"]
    assert "text match" in match["why"]  # the PR title mentions a decorator


def test_stronger_links_come_first(store, saved, sample_record):
    other = sample_record.model_copy(
        update={"id": "dr-00000001", "thread_id": "file:other", "code_links": [], "question": "Other decision"}
    )
    store.save_record(other)
    result = check_change(store, paths=["Lib/lazy.py"], description="decorator")
    assert [match["record_id"] for match in result["matches"]] == [saved.id, "dr-00000001"]
    assert result["matches"][0]["strength"] == "historical"
    assert result["matches"][1]["why"] == ["text match"]
    assert result["matches"][1]["strength"] == "suggested"


def test_record_of_the_reviewed_pr_is_direct(store, saved, sample_record):
    """A record compiled from the PR's own thread has no code link; it is that very discussion."""
    own = sample_record.model_copy(
        update={"id": "dr-00000042", "thread_id": "gh:example/widgets#42", "code_links": [], "question": "PR 42"}
    )
    store.save_record(own)
    client = httpx.Client(transport=httpx.MockTransport(github_api))
    try:
        result = check_change(store, pr_url="https://github.com/example/widgets/pull/42", client=client)
    finally:
        client.close()
    matches = {match["record_id"]: match for match in result["matches"]}
    assert matches["dr-00000042"]["strength"] == "direct"
    assert "PR #42" in matches["dr-00000042"]["why"]
    assert result["matches"][0]["record_id"] == "dr-00000042"


def test_diff_needs_a_clone_and_a_range(tmp_path, store):
    with pytest.raises(ValueError):
        check_change(store, diff="main..feature")
    with pytest.raises(ValueError):
        check_change(store, diff="main", repo_dir=tmp_path)


def test_render_report_respects_the_budget(store, saved):
    result = check_change(store, paths=["Lib/widgets.py"])
    small = render_report(result, budget_tokens=60)
    assert REPORT_TITLE in small
    assert len(small) < len(result["markdown"])
