"""Link decision records to code.

Two kinds of link need no git. Paths and GitHub blob URLs mentioned in posts
are ``direct`` links: the thread itself names the file. The files a pull
request changed are ``historical`` links: a git fact about the change, not
something the discussion said. The git helpers work on a local clone through
``subprocess``: they list the files and lines a change touches, blame those
lines at the base commit, read PR numbers from the blamed commits' messages,
and follow a file back through renames. Blame, like PR files, only ever gives
historical evidence. Text search (``suggested``) lives elsewhere.

This module imports only the standard library and ``decrack.models``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

from decrack.models import CodeLink, Thread

SOURCE_EXTENSIONS = tuple("py pyi c h cpp rs go js ts java rst md toml cfg ini txt yml yaml json".split())

# Any URL. Paths inside URLs are blanked out before the plain-path scan, so they count once.
URL_RE = re.compile(r"(?:https?://|www\.|github\.com/)[^\s<>()\[\]{}\"'`]+")
BLOB_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)/blob/([^/]+)/([^#?]+)")
# A relative path with at least one "/" that ends in a known extension, not inside a longer token.
PATH_RE = re.compile(
    r"(?<![\w./-])(?:\./)?((?:[\w.-]+/)+[\w.-]*?\.(?:" + "|".join(SOURCE_EXTENSIONS) + r"))(?![\w/-]|\.\w)"
)
SHA_RE = re.compile(r"[0-9a-f]{40}")
# "(#123)" and "gh-123"; the second also covers cpython's "(GH-123)".
PR_RE = re.compile(r"\(#(\d+)\)|\bgh-(\d+)\b", re.IGNORECASE)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
BLAME_HEADER_RE = re.compile(r"^([0-9a-f]{40}) \d+ \d+", re.MULTILINE)
ZERO_SHA = "0" * 40  # git blame's id for lines that are not committed yet
GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


# Links from the thread itself ---------------------------------------------------------


def mentioned_links(thread: Thread) -> list[CodeLink]:
    """Paths and GitHub blob URLs mentioned in the posts, as ``direct`` links.

    One link per path, in first-seen order. A later mention of the same path
    can fill in the repo or commit that the first one lacked.
    """
    thread_repo = str(thread.meta.get("repo") or "")
    links: list[CodeLink] = []
    by_path: dict[str, CodeLink] = {}
    for post in thread.posts:
        found: list[tuple[int, CodeLink]] = []
        for match in URL_RE.finditer(post.text):
            link = _blob_link(match.group(0))
            if link is not None:
                found.append((match.start(), link))
        masked = URL_RE.sub(lambda m: " " * len(m.group(0)), post.text)
        for match in PATH_RE.finditer(masked):
            path = _strip_prefixes(match.group(1))
            if path:
                link = CodeLink(repo=thread_repo, path=path, method="mentioned", strength="direct")
                found.append((match.start(), link))
        for _, link in sorted(found, key=lambda pair: pair[0]):
            _keep_link(links, by_path, link)
    return links


def pr_file_links(thread: Thread) -> list[CodeLink]:
    """The files a GitHub pull request changed, as ``historical`` links; [] for other threads.

    ``thread.meta["number"]`` is the pull request's own number, not a post position.
    """
    if thread.kind != "github_pr":
        return []
    repo = str(thread.meta.get("repo") or "")
    number = thread.meta.get("number")
    pr = int(number) if number is not None else None
    links: list[CodeLink] = []
    seen: set[str] = set()
    for value in thread.meta.get("files") or []:
        path = str(value).strip()
        if path and path not in seen:
            seen.add(path)
            links.append(CodeLink(repo=repo, path=path, pr=pr, method="pr_files", strength="historical"))
    return links


def _blob_link(url: str) -> CodeLink | None:
    """A link for ``https://github.com/<o>/<r>/blob/<ref>/<path>``; None for any other URL."""
    match = BLOB_RE.match(url)
    if match is None:
        return None
    owner, name, ref, path = match.groups()
    path = unquote(path).rstrip(".,;:!?")  # sentence punctuation right after the URL
    if not path:
        return None
    commit = ref if SHA_RE.fullmatch(ref) else None  # a branch or tag name is not an anchor
    return CodeLink(repo=f"{owner}/{name}", path=path, commit=commit, method="mentioned", strength="direct")


def _strip_prefixes(path: str) -> str:
    """Drop a leading ``./`` and git's ``a/`` or ``b/`` diff prefix."""
    if path.startswith("./"):
        path = path[2:]
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def _keep_link(links: list[CodeLink], by_path: dict[str, CodeLink], link: CodeLink) -> None:
    kept = by_path.get(link.path)
    if kept is None:
        by_path[link.path] = link
        links.append(link)
        return
    if not kept.repo and link.repo:
        kept.repo = link.repo
    if kept.commit is None and link.commit is not None and kept.repo == link.repo:
        kept.commit = link.commit


# Local git ----------------------------------------------------------------------------


def git(repo_dir: str | Path, *args: str) -> str:
    """Run ``git -C repo_dir *args`` and return stdout; RuntimeError with git's stderr on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is not installed or not on PATH") from exc
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def changed_files(repo_dir: str | Path, base: str, head: str) -> list[str]:
    """Paths changed between two commits, sorted; a rename contributes its old and new path."""
    output = git(repo_dir, "diff", "--name-status", "-M", "--no-color", base, head, "--")
    return sorted(set(_name_status_paths(output)))


def changed_line_ranges(repo_dir: str | Path, base: str, head: str) -> dict[str, list[tuple[int, int]]]:
    """For each file changed between two commits, the line ranges it had at ``base`` that changed.

    Keyed by the old path. A pure insertion gives the line above it, the line
    whose history the new code joins. New files have no old lines and are left out.
    """
    output = git(
        repo_dir,
        "diff",
        "-U0",
        "-M",
        "--no-color",
        "--no-ext-diff",
        "--src-prefix=a/",  # fixed prefixes, whatever diff.noprefix says
        "--dst-prefix=b/",
        base,
        head,
        "--",
    )
    ranges: dict[str, list[tuple[int, int]]] = {}
    path: str | None = None
    in_header = False
    # split("\n"), not splitlines(): source lines may hold form feeds and other separators.
    for line in output.split("\n"):
        if line.startswith("diff --git "):
            path, in_header = None, True
        elif in_header and line.startswith("--- "):
            name = line[4:].rstrip("\t")  # git appends a tab to names that contain spaces
            path = name[2:] if name.startswith("a/") else None  # None for /dev/null
        elif line.startswith("@@"):
            in_header = False
            match = HUNK_RE.match(line)
            if path is None or match is None:
                continue
            start = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            if count > 0:
                ranges.setdefault(path, []).append((start, start + count - 1))
            elif start > 0:
                ranges.setdefault(path, []).append((start, start))
    return ranges


def blame_commits(repo_dir: str | Path, rev: str, path: str, ranges: list[tuple[int, int]]) -> set[str]:
    """Commits that last touched the given line ranges of ``path`` at ``rev``.

    Ranges git rejects, such as one that starts past the end of the file, are skipped.
    """
    commits: set[str] = set()
    for start, end in ranges:
        try:
            output = git(repo_dir, "blame", "-w", "-C", "-M", "--porcelain", "-L", f"{start},{end}", rev, "--", path)
        except RuntimeError:
            continue
        commits.update(sha for sha in BLAME_HEADER_RE.findall(output) if sha != ZERO_SHA)
    return commits


def pr_numbers(message: str) -> list[int]:
    """Sorted PR (or issue) numbers written as ``(#123)``, ``(GH-123)`` or ``gh-123``."""
    return sorted({int(hash_form or gh_form) for hash_form, gh_form in PR_RE.findall(message)})


def commit_prs(repo_dir: str | Path, commits: list[str] | set[str]) -> dict[str, list[int]]:
    """PR numbers named in each commit's message."""
    return {sha: pr_numbers(git(repo_dir, "log", "-1", "--format=%B", sha, "--")) for sha in commits}


def follow_renames(repo_dir: str | Path, path: str) -> list[str]:
    """Every name ``path`` has had, starting with ``path`` itself, newest first."""
    output = git(repo_dir, "log", "--follow", "--name-status", "--no-color", "--format=", "--", path)
    names = [path]
    for name in _name_status_paths(output):
        if name not in names:
            names.append(name)
    return names


def prs_for_change(repo_dir: str | Path, base: str, head: str) -> tuple[list[str], list[int]]:
    """The paths a change touches, and the PRs that last touched its changed lines at ``base``."""
    paths = changed_files(repo_dir, base, head)
    commits: set[str] = set()
    for path, ranges in changed_line_ranges(repo_dir, base, head).items():
        commits |= blame_commits(repo_dir, base, path, ranges)
    numbers = commit_prs(repo_dir, sorted(commits))
    return paths, sorted({number for found in numbers.values() for number in found})


def origin_repo(repo_dir: str | Path) -> str | None:
    """``owner/name`` of the clone's ``origin`` remote when it is on GitHub, else None."""
    try:
        url = git(repo_dir, "remote", "get-url", "origin").strip()
    except RuntimeError:
        return None
    match = GITHUB_REMOTE_RE.search(url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def _name_status_paths(output: str) -> list[str]:
    """Paths from ``--name-status`` lines: ``M<tab>path`` or ``R087<tab>old<tab>new``."""
    paths: list[str] = []
    for line in output.split("\n"):
        status, *names = line.split("\t")
        if not status or not names:
            continue
        paths.extend(names[:2] if status[0] in "RC" else names[:1])
    return [path for path in paths if path]
