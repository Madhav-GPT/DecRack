"""Read a discussion saved in a local file into a Thread.

Accepted shapes, read forgivingly:

* ``.json``: a list of posts, an object ``{"title", "posts", "url", "created_by"}``,
  or a Discourse topic JSON (anything with ``post_stream``);
* ``.jsonl``: one post object per line;
* a Discourse raw export, whose posts start with ``alice | 2025-01-05 10:00:00 UTC | #1``;
* plain Markdown or text, split into posts on ``---`` / ``***`` / ``___`` lines,
  where a post may open with an author line (``alice:``, ``**alice**`` or ``@alice``).

Post objects may name their fields ``author``/``username``/``user``,
``text``/``body``/``raw``/``content`` (or HTML ``cooked``) and
``created_at``/``date``/``timestamp``; a valid ``role`` is kept.

A post's id is ``file:{sha8}:{n}``: sha8 is the first 8 hex digits of the
sha256 of the file's bytes, and n is the post's position among the file's
posts (empty ones skipped), which is also its ``source_post_number``. Editing
the file changes every id, so a citation never silently moves to other text.
A Discourse topic JSON keeps its Discourse ids (``dpo:...``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from decrack.models import ROLES, Post, Thread
from decrack.sources.discourse import cooked_to_text, topic_to_thread
from decrack.text import finalize_thread, parse_time

DEFAULT_FORUM = "https://discuss.python.org"
JSONL_SUFFIXES = {".jsonl", ".ndjson"}
AUTHOR_KEYS = ("author", "username", "user")
TEXT_KEYS = ("text", "body", "raw", "content")
TIME_KEYS = ("created_at", "date", "timestamp")
NO_AUTHOR = "unknown"

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
TITLE_RE = re.compile(r"^\s{0,3}#\s+(.+?)(?:\s+#+)?\s*$")
EXPORT_HEADER_RE = re.compile(
    r"^\s*(?P<user>[^|\s][^|]*?)\s*\|\s*(?P<time>\d{4}-\d{2}-\d{2}[^|]*?)\s*\|\s*#(?P<number>\d+)\s*$"
)
DASH_LINE_RE = re.compile(r"^\s*-{3,}\s*$")
SEPARATOR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_NAME = r"\w[\w.' -]{0,39}?"
AUTHOR_LINE_RE = re.compile(
    rf"^(?:\*\*\s*(?P<bold>{_NAME})\s*:?\s*\*\*\s*:?|(?P<plain>{_NAME})\s*:|@(?P<at>[\w.-]+):?)$"
)
BBCODE_QUOTE_RE = re.compile(r"\[quote(?:=[^\]]*)?\].*?\[/quote\]", re.DOTALL | re.IGNORECASE)


def load_file(path: str | Path) -> Thread:
    """Read a local discussion file (see the module docstring for the shapes it accepts)."""
    file = Path(path).expanduser()
    if not file.is_file():
        raise FileNotFoundError(f"No such file: {file}")
    data = file.read_bytes()
    sha8 = hashlib.sha256(data).hexdigest()[:8]
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{file} is not UTF-8 text") from exc
    content = content.replace("\r\n", "\n").replace("\r", "\n")  # the same line ends as reading in text mode
    suffix = file.suffix.lower()
    if suffix == ".json":
        return _from_json(file, sha8, _parse_json(content, file))
    if suffix in JSONL_SUFFIXES:
        return _from_jsonl(file, sha8, content)
    return _from_text(file, sha8, content)


def _parse_json(content: str, file: Path, line: int | None = None) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        where = f"{file} line {line}" if line else str(file)
        raise ValueError(f"{where} is not valid JSON: {exc}") from exc


def _from_json(file: Path, sha8: str, data: Any) -> Thread:
    if isinstance(data, list):
        posts = [_json_post(item, f"{file.name} post {index}") for index, item in enumerate(data, start=1)]
        return _thread(file, sha8, None, "", posts, [])
    if not isinstance(data, dict):
        raise ValueError(f"{file} holds a JSON {type(data).__name__}; expected a list of posts or an object")
    if "post_stream" in data:
        # A saved Discourse topic: its posts keep the ids they have on the forum.
        return finalize_thread(topic_to_thread(data, str(data.get("forum") or DEFAULT_FORUM)))
    items = data.get("posts")
    if not isinstance(items, list):
        raise ValueError(f"{file} has neither a 'posts' list nor a Discourse 'post_stream'")
    posts = [_json_post(item, f"{file.name} post {index}") for index, item in enumerate(items, start=1)]
    title = data.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else None
    return _thread(file, sha8, title, str(data.get("url") or ""), posts, _creators(data))


def _from_jsonl(file: Path, sha8: str, content: str) -> Thread:
    posts = [
        _json_post(_parse_json(line, file, number), f"{file.name} line {number}")
        for number, line in enumerate(content.splitlines(), start=1)
        if line.strip()
    ]
    return _thread(file, sha8, None, "", posts, [])


def _first(item: dict[str, Any], keys: tuple[str, ...], convert: Callable[[Any], Any]) -> Any:
    """The first non-empty converted value among ``keys``, else None."""
    for key in keys:
        value = convert(item.get(key))
        if value:
            return value
    return None


def _name(value: Any) -> str:
    """A person's name from a string or a user object (``login``, ``username`` or ``name``)."""
    if isinstance(value, dict):
        value = value.get("login") or value.get("username") or value.get("name")
    return value.strip() if isinstance(value, str) else ""


def _string(value: Any) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _json_post(item: Any, where: str) -> dict[str, Any]:
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict):
        raise ValueError(f"{where} is not a post object")
    text = _first(item, TEXT_KEYS, _string)
    if not text and isinstance(item.get("cooked"), str):
        text = cooked_to_text(item["cooked"])[0]
    role = str(item.get("role") or "").strip().lower()
    return _post(
        _first(item, AUTHOR_KEYS, _name) or NO_AUTHOR,
        text or "",
        _first(item, TIME_KEYS, parse_time),
        role if role in ROLES else "unknown",
        str(item.get("url") or ""),
    )


def _creators(data: dict[str, Any]) -> list[str]:
    """Names from a top-level ``created_by`` or ``author`` (a name, a user object or a list)."""
    for key in ("created_by", "author"):
        value = data.get(key)
        names = [_name(entry) for entry in (value if isinstance(value, list) else [value])]
        names = [name for name in names if name and name.casefold() != NO_AUTHOR]
        if names:
            return names
    return []


def _post(
    author: str, text: str, created_at: datetime | None = None, role: str = "unknown", url: str = ""
) -> dict[str, Any]:
    # A quote block repeats an earlier writer's words; kept, they would be credited to the quoter.
    clean = BBCODE_QUOTE_RE.sub("", text).strip()
    return {"author": author or NO_AUTHOR, "text": clean, "created_at": created_at, "role": role, "url": url}


def _fenced(lines: list[str]) -> list[bool]:
    """Whether each line belongs to a fenced code block, fence lines included."""
    mask: list[bool] = []
    marker: str | None = None
    for line in lines:
        if marker is None:
            match = FENCE_RE.match(line)
            marker = match.group(1) if match else None
            mask.append(match is not None)
            continue
        mask.append(True)
        stripped = line.strip()
        if stripped.startswith(marker) and stripped == stripped[0] * len(stripped):
            marker = None
    return mask


def _heading(lines: list[str], fenced: list[bool]) -> tuple[int, str] | None:
    """Index and text of the first ``# heading`` line outside code."""
    for index, (line, in_code) in enumerate(zip(lines, fenced)):
        match = None if in_code else TITLE_RE.match(line)
        if match:
            return index, match.group(1).strip()
    return None


def _from_text(file: Path, sha8: str, content: str) -> Thread:
    lines = content.splitlines()
    fenced = _fenced(lines)
    headers = [i for i, line in enumerate(lines) if not fenced[i] and EXPORT_HEADER_RE.match(line)]
    if headers:
        heading = _heading(lines[: headers[0]], fenced[: headers[0]])
        return _thread(file, sha8, heading[1] if heading else None, "", _export_posts(lines, fenced), [])
    heading = _heading(lines, fenced)
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if heading and heading[0] == first:
        # The title opens the file: it names the discussion and is nobody's post.
        del lines[first], fenced[first]
    return _thread(file, sha8, heading[1] if heading else None, "", _plain_posts(lines, fenced), [])


def _export_posts(lines: list[str], fenced: list[bool]) -> list[dict[str, Any]]:
    """Posts of a Discourse raw export: each header starts one; dash separator lines are dropped."""
    found: list[tuple[str, datetime | None, list[str]]] = []
    for line, in_code in zip(lines, fenced):
        header = None if in_code else EXPORT_HEADER_RE.match(line)
        if header:
            found.append((header.group("user").strip(), parse_time(header.group("time")), []))
        elif found and (in_code or not DASH_LINE_RE.match(line)):
            found[-1][2].append(line)
    return [_post(author, "\n".join(body), created) for author, created, body in found]


def _plain_posts(lines: list[str], fenced: list[bool]) -> list[dict[str, Any]]:
    """Posts split on separator lines; an opening author line names the writer and is removed."""
    chunks: list[list[str]] = [[]]
    for line, in_code in zip(lines, fenced):
        if not in_code and SEPARATOR_RE.match(line):
            chunks.append([])
        else:
            chunks[-1].append(line)
    posts: list[dict[str, Any]] = []
    for chunk in chunks:
        author = NO_AUTHOR
        first = next((i for i, line in enumerate(chunk) if line.strip()), None)
        match = AUTHOR_LINE_RE.match(chunk[first].strip()) if first is not None else None
        if match:
            author = next(name for name in match.group("bold", "plain", "at") if name).strip()
            chunk = chunk[:first] + chunk[first + 1 :]
        posts.append(_post(author, "\n".join(chunk)))
    return posts


def _thread(
    file: Path, sha8: str, title: str | None, url: str, raw_posts: list[dict[str, Any]], creators: list[str]
) -> Thread:
    """Drop empty posts, number them in file order, order them by time when every post has one, and finalize."""
    kept = [post for post in raw_posts if post["text"]]
    if not kept:
        raise ValueError(f"No posts with text found in {file}")
    numbered = list(enumerate(kept, start=1))  # (position in the file, post)
    if all(post["created_at"] is not None for post in kept):
        numbered.sort(key=lambda item: item[1]["created_at"])  # stable: equal times keep file order
    source_id = f"file:{sha8}"
    posts = [
        Post(id=f"{source_id}:{position}", source_id=source_id, source_post_number=position, seq=seq, version=1, **post)
        for seq, (position, post) in enumerate(numbered, start=1)
    ]
    stem = file.stem
    if not creators and posts[0].author.casefold() != NO_AUTHOR:
        creators = [posts[0].author]
    thread = Thread(
        id=f"file:{stem}",
        kind="file",
        url=url,
        title=title or stem,
        posts=posts,
        meta={"created_by": creators, "path": file.name},
    )
    return finalize_thread(thread)
