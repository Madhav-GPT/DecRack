"""Read a GitHub issue or pull request into a Thread.

Post 1 is the issue body; after it come the comments, the reviews that have a
body and the review comments, ordered by time. Post ids are GitHub's own:
``gh:{owner}/{repo}#{n}`` for the body, then ``:c{id}``, ``:r{id}`` and
``:rc{id}`` appended for comments, reviews and review comments. Every post's
``source_id`` is the issue or PR (``gh:{owner}/{repo}#{n}``); GitHub has no
per-thread post numbers, so ``source_post_number`` is None, and ``version`` is 1.

Roles stay "unknown": the pipeline fills them from ``author_association`` and
the thread's ``opener``, ``merged_by`` and ``closed_by``. A token in
``GITHUB_TOKEN`` is optional; it only raises the API rate limit.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from decrack.models import Post, Thread
from decrack.text import finalize_thread, parse_time

GITHUB_API = "https://api.github.com"
API_VERSION = "2022-11-28"

_NAME = r"[A-Za-z0-9_.-]+"
URL_RE = re.compile(
    rf"^(?:https?://)?(?:www\.)?github\.com/({_NAME})/({_NAME})/(?:issues|pull)/(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
SHORT_RE = re.compile(rf"^(?:gh:)?({_NAME})/({_NAME})#(\d+)$", re.IGNORECASE)
REPO_URL_RE = re.compile(rf"^(?:https?://)?(?:www\.)?github\.com/({_NAME})/({_NAME})/?$", re.IGNORECASE)
API_ITEM_RE = re.compile(r"/repos/([^/]+)/([^/]+)/(?:issues|pulls)/(\d+)")
# PR templates leave HTML comments that GitHub never shows; they are not part of the discussion.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
NO_TIME = datetime.max.replace(tzinfo=timezone.utc)


def parse_github_ref(ref: str) -> tuple[str, str, int]:
    """``(owner, repo, number)`` from an issue or PR URL, ``o/r#n`` or ``gh:o/r#n``."""
    value = ref.strip() if isinstance(ref, str) else ""
    match = URL_RE.match(value) or SHORT_RE.match(value)
    if match is None:
        raise ValueError(f"Not a GitHub issue or pull request reference: {ref!r}")
    owner, repo, number = match.group(1), match.group(2), int(match.group(3))
    # A name made only of dots would walk up the API path instead of naming a repository.
    if number < 1 or not owner.strip(".") or not repo.strip("."):
        raise ValueError(f"Not a GitHub issue or pull request reference: {ref!r}")
    return owner, repo, number


def is_github_ref(ref: str) -> bool:
    """True when ``ref`` names a GitHub issue or pull request."""
    try:
        parse_github_ref(ref)
    except ValueError:
        return False
    return True


def parse_repo_url(value: str) -> tuple[str, str] | None:
    """``(owner, repo)`` for a bare repository URL such as ``https://github.com/python/cpython``, else None."""
    match = REPO_URL_RE.match((value or "").strip())
    if match is None:
        return None
    owner, repo = match.group(1), match.group(2)
    repo = repo[:-4] if repo.lower().endswith(".git") else repo
    return (owner, repo) if owner.strip(".") and repo.strip(".") else None


def search_threads(owner: str, repo: str, keywords: list[str], client: httpx.Client, limit: int = 3) -> list[str]:
    """URLs of the ``limit`` issues and PRs of owner/repo that best match ``keywords``, by GitHub's search API."""
    query = " ".join([f"repo:{owner}/{repo}", *keywords])
    data = _get_json(client, f"{GITHUB_API}/search/issues", params={"q": query, "per_page": limit})
    items = data.get("items") if isinstance(data, dict) else None
    return [item["html_url"] for item in (items or [])[:limit] if isinstance(item, dict) and item.get("html_url")]


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _item_name(url: str) -> str:
    """``o/r#n`` for an API URL of an issue or pull request, else the URL itself."""
    match = API_ITEM_RE.search(url)
    return f"{match.group(1)}/{match.group(2)}#{match.group(3)}" if match else url


def _check(response: httpx.Response, url: str) -> None:
    """Turn GitHub's common failures into errors a user can act on."""
    if response.status_code in (403, 429):
        raise RuntimeError(
            f"GitHub refused {url} with HTTP {response.status_code}: the GitHub rate limit was hit "
            "(or access was denied). Set GITHUB_TOKEN to a GitHub token to raise the limit and retry."
        )
    if response.status_code == 404:
        raise ValueError(
            f"GitHub issue or pull request {_item_name(url)} was not found (HTTP 404 for {url}). "
            "Check the reference, or set GITHUB_TOKEN if the repository is private."
        )
    response.raise_for_status()


def _get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    """GET one GitHub API URL and return its decoded JSON."""
    response = client.get(url, params=params, headers=_headers())
    _check(response, url)
    return response.json()


def _get_list(client: httpx.Client, url: str) -> list[dict[str, Any]]:
    """Every item of a paginated GitHub list, following the ``Link: rel="next"`` header."""
    items: list[dict[str, Any]] = []
    params: dict[str, Any] | None = {"per_page": 100}
    next_url: str | None = url
    seen: set[str] = set()
    while next_url and next_url not in seen:
        seen.add(next_url)
        response = client.get(next_url, params=params, headers=_headers())
        _check(response, next_url)
        page = response.json()
        if not isinstance(page, list):
            raise ValueError(f"GitHub returned {type(page).__name__} instead of a list for {next_url}")
        items.extend(item for item in page if isinstance(item, dict))
        next_url = response.links.get("next", {}).get("url")
        params = None  # the next link already carries per_page and page
    return items


def _as_dict(value: Any, url: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"GitHub returned {type(value).__name__} instead of an object for {url}")
    return value


def _login(user: Any) -> str | None:
    if isinstance(user, dict) and user.get("login"):
        return str(user["login"])
    return None


def _text(value: Any) -> str:
    """A body as plain text: CRLF line ends normalized, hidden HTML comments dropped."""
    if not isinstance(value, str):
        return ""
    return HTML_COMMENT_RE.sub("", value.replace("\r\n", "\n")).strip()


def _labels(value: Any) -> list[str]:
    names: list[str] = []
    for label in value or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _entry(post_id: str, item: dict[str, Any], kind: str, created: Any, **extra: Any) -> dict[str, Any]:
    """Keyword arguments for one Post, without its place in the thread."""
    return {
        "id": post_id,
        "author": _login(item.get("user")) or "ghost",
        "created_at": parse_time(created),
        "url": str(item.get("html_url") or ""),
        "text": _text(item.get("body")),
        "meta": {"author_association": str(item.get("author_association") or "NONE"), "kind": kind, **extra},
    }


def load_github(ref: str, client: httpx.Client) -> Thread:
    """Fetch an issue or pull request with its comments, reviews and review comments."""
    owner, repo, number = parse_github_ref(ref)
    root = f"{GITHUB_API}/repos/{owner}/{repo}"
    issue_url = f"{root}/issues/{number}"
    issue = _as_dict(_get_json(client, issue_url), issue_url)
    comments = _get_list(client, f"{issue_url}/comments")

    is_pr = issue.get("pull_request") is not None
    pull: dict[str, Any] = {}
    reviews: list[dict[str, Any]] = []
    review_comments: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    if is_pr:
        pull_url = f"{root}/pulls/{number}"
        pull = _as_dict(_get_json(client, pull_url), pull_url)
        reviews = _get_list(client, f"{pull_url}/reviews")
        review_comments = _get_list(client, f"{pull_url}/comments")
        files = _get_list(client, f"{pull_url}/files")

    thread_id = f"gh:{owner}/{repo}#{number}"
    body = _entry(thread_id, issue, "body", issue.get("created_at"))
    others = [_entry(f"{thread_id}:c{item.get('id')}", item, "comment", item.get("created_at")) for item in comments]
    others += [
        _entry(
            f"{thread_id}:r{item.get('id')}",
            item,
            "review",
            item.get("submitted_at"),
            review_state=str(item.get("state") or ""),
        )
        for item in reviews
        if _text(item.get("body"))
    ]
    others += [
        _entry(
            f"{thread_id}:rc{item.get('id')}",
            item,
            "review_comment",
            item.get("created_at"),
            path=str(item.get("path") or ""),
        )
        for item in review_comments
    ]
    others.sort(key=lambda entry: entry["created_at"] or NO_TIME)  # stable: ties keep fetch order
    posts = [
        Post(source_id=thread_id, source_post_number=None, seq=seq, version=1, **entry)
        for seq, entry in enumerate([body, *others], start=1)
    ]

    meta: dict[str, Any] = {
        "repo": f"{owner}/{repo}",
        "number": number,
        "state": issue.get("state"),
        "state_reason": issue.get("state_reason"),
        "merged": bool(pull.get("merged")),
        "merged_at": pull.get("merged_at"),
        "merged_by": _login(pull.get("merged_by")),
        "closed_by": _login(issue.get("closed_by")),
        "labels": _labels(issue.get("labels")),
        "files": [str(item["filename"]) for item in files if item.get("filename")],
        "opener": body["author"],
        "reviews": [
            {
                "user": _login(item.get("user")) or "ghost",
                "state": item.get("state"),
                "author_association": item.get("author_association"),
            }
            for item in reviews
        ],
    }
    page = "pull" if is_pr else "issues"
    thread = Thread(
        id=thread_id,
        kind="github_pr" if is_pr else "github_issue",
        url=str(issue.get("html_url") or f"https://github.com/{owner}/{repo}/{page}/{number}"),
        title=str(issue.get("title") or ""),
        posts=posts,
        meta=meta,
    )
    return finalize_thread(thread)


def pr_summary(ref: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """Owner, repo, number, title, body, changed files and merge state of a pull request."""
    owner, repo, number = parse_github_ref(ref)
    http = client if client is not None else httpx.Client(timeout=30, follow_redirects=True)
    root = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        issue_url = f"{root}/issues/{number}"
        pull_url = f"{root}/pulls/{number}"
        issue = _as_dict(_get_json(http, issue_url), issue_url)
        pull = _as_dict(_get_json(http, pull_url), pull_url)
        files = _get_list(http, f"{pull_url}/files")
    finally:
        if client is None:
            http.close()
    return {
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": str(issue.get("title") or ""),
        "body": _text(issue.get("body")),
        "files": [str(item["filename"]) for item in files if item.get("filename")],
        "merged": bool(pull.get("merged")),
    }
