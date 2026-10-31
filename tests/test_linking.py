"""Code links: mentions (direct) and PR files (historical) from a thread, and the git helpers on a temp repo."""

from __future__ import annotations

import shutil

import pytest

from decrack import linking
from decrack.models import CodeLink, Post, Thread

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

LINES = [
    "def make_widget(name):",
    "    return {'name': name}",
    "",
    "",
    "def lazy_widget(name):",
    "    return make_widget(name)",
    "",
    "",
    "WIDGET_KINDS = ('plain', 'lazy')",
]
EDITED_LINE = 6  # the line the third commit changes


def make_thread(texts: list[str], kind: str = "discourse", meta: dict | None = None) -> Thread:
    posts = [
        Post(id=f"file:0a1b2c3d:{seq}", source_id="file:0a1b2c3d", seq=seq, author="someone", text=text)
        for seq, text in enumerate(texts, start=1)
    ]
    return Thread(id="file:links", kind=kind, posts=posts, meta=meta or {})


def write_lines(path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def repo(tmp_path):
    """Three commits: add Lib/widgets.py (#12), rename it to Lib/lazy.py (GH-34), edit one line (gh-56)."""
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args: str) -> str:
        return linking.git(root, *args)

    git("init", "-q")
    git("config", "user.name", "Test Author")
    git("config", "user.email", "author@example.com")
    git("config", "commit.gpgsign", "false")
    (root / "Lib").mkdir()
    write_lines(root / "Lib" / "widgets.py", LINES)
    git("add", "Lib/widgets.py")
    git("commit", "-q", "--no-verify", "-m", "Add widgets (#12)")
    first = git("rev-parse", "HEAD").strip()
    git("mv", "Lib/widgets.py", "Lib/lazy.py")
    git("commit", "-q", "--no-verify", "-m", "Rename module (GH-34)")
    second = git("rev-parse", "HEAD").strip()
    edited = list(LINES)
    edited[EDITED_LINE - 1] = "    return make_widget(name.lower())"
    write_lines(root / "Lib" / "lazy.py", edited)
    git("commit", "-q", "--no-verify", "-a", "-m", "gh-56: Lower-case widget names")
    third = git("rev-parse", "HEAD").strip()
    return root, first, second, third


def test_mentioned_links_reads_blob_urls_and_paths():
    sha = "a1" * 20
    thread = make_thread(
        [
            f"See https://github.com/example/widgets/blob/{sha}/Lib/widgets.py#L10-L20 for the current code.",
            "The fix belongs in `Lib/foo.py`, next to ./Doc/library/foo.rst.",
            "The diff touched a/Lib/foo.py and b/Lib/foo.py, and "
            "https://github.com/example/widgets/blob/main/Lib/bar.py.",
            "Nothing here: Lib/foo.pyc, notes.txt and https://example.com/Lib/skip.py are not repo paths.",
        ]
    )
    links = linking.mentioned_links(thread)
    assert [link.path for link in links] == ["Lib/widgets.py", "Lib/foo.py", "Doc/library/foo.rst", "Lib/bar.py"]
    assert links[0] == CodeLink(
        repo="example/widgets", path="Lib/widgets.py", commit=sha, method="mentioned", strength="direct"
    )
    # A branch name is not a commit anchor, and a plain mention has no repo in a forum thread.
    assert (links[3].repo, links[3].commit) == ("example/widgets", None)
    assert (links[1].repo, links[1].commit) == ("", None)
    # The thread names these files itself, so every mention is a direct link.
    assert all(link.method == "mentioned" and link.strength == "direct" for link in links)


def test_mentioned_links_fill_in_repo_from_a_later_url():
    thread = make_thread(
        [
            "Lib/widgets.py is where the loader lives.",
            "Permalink: https://github.com/example/widgets/blob/" + "b2" * 20 + "/Lib/widgets.py",
        ]
    )
    [link] = linking.mentioned_links(thread)
    assert (link.repo, link.path, link.commit) == ("example/widgets", "Lib/widgets.py", "b2" * 20)
    assert link.strength == "direct"


def test_pr_file_links_only_for_pull_requests():
    # meta["number"] is the pull request's own number (not a post position).
    meta = {"repo": "example/widgets", "number": 42, "files": ["Lib/lazy.py", "Lib/widgets.py", "Lib/lazy.py"]}
    pull = make_thread(["Rename the module."], kind="github_pr", meta=meta)
    # Files a PR changed are a git fact, not something the discussion said: historical links.
    assert linking.pr_file_links(pull) == [
        CodeLink(repo="example/widgets", path="Lib/lazy.py", pr=42, method="pr_files", strength="historical"),
        CodeLink(repo="example/widgets", path="Lib/widgets.py", pr=42, method="pr_files", strength="historical"),
    ]
    issue = make_thread(["Lib/lazy.py is slow."], kind="github_issue", meta={**meta, "number": 7})
    assert linking.pr_file_links(issue) == []
    # On GitHub the thread's repo is known, so plain mentions get it.
    assert linking.mentioned_links(issue)[0].repo == "example/widgets"


def test_pr_numbers_reads_the_three_forms():
    message = "gh-101: Fix the loader (#102)\n\nAlso see GH-103 and (GH-104); issue #105 is not a PR reference."
    assert linking.pr_numbers(message) == [101, 102, 103, 104]
    assert linking.pr_numbers("Plain message without numbers") == []


@requires_git
def test_follow_renames_finds_the_old_name(repo):
    root, *_ = repo
    assert linking.follow_renames(root, "Lib/lazy.py") == ["Lib/lazy.py", "Lib/widgets.py"]


@requires_git
def test_changed_files_and_line_ranges(repo):
    root, first, second, third = repo
    assert linking.changed_files(root, second, third) == ["Lib/lazy.py"]
    # A rename lists both names; its line ranges are keyed by the old one.
    assert linking.changed_files(root, first, third) == ["Lib/lazy.py", "Lib/widgets.py"]
    assert linking.changed_line_ranges(root, second, third) == {"Lib/lazy.py": [(EDITED_LINE, EDITED_LINE)]}
    assert linking.changed_line_ranges(root, first, third) == {"Lib/widgets.py": [(EDITED_LINE, EDITED_LINE)]}
    # A pure rename changes no lines.
    assert linking.changed_line_ranges(root, first, second) == {}


@requires_git
def test_blame_commits(repo):
    root, first, second, third = repo
    # Blame follows the rename back to the commit that wrote the line.
    assert linking.blame_commits(root, third, "Lib/lazy.py", [(1, 1)]) == {first}
    assert linking.blame_commits(root, third, "Lib/lazy.py", [(EDITED_LINE, EDITED_LINE)]) == {third}
    # A range past the end of the file is skipped, not an error.
    assert linking.blame_commits(root, third, "Lib/lazy.py", [(1, 2), (500, 501)]) == {first}


@requires_git
def test_commit_prs(repo):
    root, first, second, third = repo
    assert linking.commit_prs(root, [first, second, third]) == {first: [12], second: [34], third: [56]}


@requires_git
def test_prs_for_change_blames_the_base(repo):
    root, first, second, third = repo
    # The edited line was last touched by commit 1 (the rename did not change it), so PR 12.
    assert linking.prs_for_change(root, second, third) == (["Lib/lazy.py"], [12])


@requires_git
def test_git_errors_and_origin_repo(repo):
    root, *_ = repo
    with pytest.raises(RuntimeError):
        linking.git(root, "rev-parse", "no-such-branch")
    assert linking.origin_repo(root) is None
    linking.git(root, "remote", "add", "origin", "git@github.com:example/widgets.git")
    assert linking.origin_repo(root) == "example/widgets"
