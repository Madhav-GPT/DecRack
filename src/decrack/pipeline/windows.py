"""Token-budgeted chronological windows for the MAP step.

Every post with sentences becomes one part. A post whose rendered block is
larger than half the budget is cut at sentence boundaries into several parts;
they share the post and keep post-global sentence indexes. Parts fill a window
in thread order up to ``max_tokens`` estimated tokens of rendered prompt text
(a single part above the budget, which only a huge sentence can be, gets a
window of its own). Each window after the first starts with the last whole
parts of the previous one, about ``overlap_tokens`` and at least one, so a
reply is read next to what it answers. The overlap is context only: it shrinks
when needed so that every window reads at least one new part.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import NamedTuple

from decrack.models import Post, Thread
from decrack.pipeline.prompts import render_part
from decrack.text import estimate_tokens, sha256_text

CHUNKER_VERSION = "decrack-windows-2"


class WindowPart(NamedTuple):
    """Sentences ``first_index``..``last_index`` (1-based, post-global) of one post."""

    post: Post
    first_index: int
    last_index: int


@dataclass
class Window:
    id: str
    index: int
    parts: list[WindowPart]
    tokens: int  # estimated tokens of the rendered parts

    @property
    def posts(self) -> list[Post]:
        """The distinct posts of the window, in order."""
        seen: set[str] = set()
        posts: list[Post] = []
        for part in self.parts:
            if part.post.id not in seen:
                seen.add(part.post.id)
                posts.append(part.post)
        return posts


def part_tokens(part: WindowPart, thread: Thread | None = None) -> int:
    """Estimated tokens of the part as the model sees it."""
    return estimate_tokens(render_part(part.post, part.first_index, part.last_index, thread))


def part_ref(part: WindowPart) -> list:
    """``[post_id, version, sha256, first_index, last_index]``: the identity of a part's input."""
    post = part.post
    return [post.id, post.version, post.sha256 or sha256_text(post.text), part.first_index, part.last_index]


def window_id(parts: list[WindowPart]) -> str:
    """sha256 hex of the chunker version and every part's ``part_ref``.

    A new reply therefore changes only the id of the window it lands in, and an
    edited post (new text, so a new sha256, or a new version) the ids of its windows.
    """
    refs = [part_ref(part) for part in parts]
    payload = json.dumps([CHUNKER_VERSION, refs], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def split_post(post: Post, thread: Thread | None, limit: float) -> list[WindowPart]:
    """The whole post as one part when it fits ``limit`` tokens, else runs of whole sentences that do.

    A run grows sentence by sentence until the next one would push it over the
    limit; a single sentence above the limit stays whole, as a part of its own.
    """
    whole = WindowPart(post, 1, len(post.sentences))
    if part_tokens(whole, thread) <= limit:
        return [whole]
    parts: list[WindowPart] = []
    first = 1
    for index in range(2, len(post.sentences) + 1):
        if part_tokens(WindowPart(post, first, index), thread) > limit:
            parts.append(WindowPart(post, first, index - 1))
            first = index
    parts.append(WindowPart(post, first, len(post.sentences)))
    return parts


def make_windows(thread: Thread, max_tokens: int = 6000, overlap_tokens: int = 800) -> list[Window]:
    """Split the thread's posts (those with sentences) into overlapping token-budgeted windows."""
    max_tokens = max(1, max_tokens)
    overlap_tokens = max(0, overlap_tokens)
    posts = sorted((post for post in thread.posts if post.sentences), key=lambda post: post.seq)
    parts = [part for post in posts for part in split_post(post, thread, max_tokens / 2)]
    prefix = [0]  # prefix[i] = tokens of parts[:i]
    for part in parts:
        prefix.append(prefix[-1] + part_tokens(part, thread))

    def total(first: int, end: int) -> int:
        """Tokens of ``parts[first:end]``."""
        return prefix[end] - prefix[first]

    windows: list[Window] = []
    start = 0
    while start < len(parts):
        end = start + 1  # a window always takes its first part, even one above max_tokens
        while end < len(parts) and total(start, end + 1) <= max_tokens:
            end += 1
        chunk = parts[start:end]
        windows.append(Window(id=window_id(chunk), index=len(windows), parts=chunk, tokens=total(start, end)))
        if end >= len(parts):
            break
        # Overlap: the last part of this window, plus earlier ones while they stay within overlap_tokens.
        next_start = end - 1
        while next_start > start and total(next_start - 1, end) <= overlap_tokens:
            next_start -= 1
        # Shrink the overlap until the first unread part fits beside it, so every window reads a new part.
        # With parts of at most half the budget this keeps at least one part of overlap.
        while next_start < end and total(next_start, end + 1) > max_tokens:
            next_start += 1
        start = next_start
    return windows
