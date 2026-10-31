"""Roles from metadata, and decision cues.

``assign_roles`` fills every post whose role is still "unknown" from thread
and post metadata, never from what a post says about its writer. Explicit
roles (from an export or a test) are kept, so calling it twice is harmless.

``cue_score`` counts phrases that often mark a decision ("rejected ideas",
"instead of", "-1", ...). Cues only order the hints given to the model; they
never drop a post.
"""

from __future__ import annotations

import re
from typing import Any

from decrack.models import Thread

MEMBER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
# Placeholder names never make anyone an author: a plain-text file without author
# lines gives every post the author "unknown", and they must not all become "author".
NO_NAMES = {"", "unknown"}

CUE_PHRASES = (
    r"rejected ideas?",
    r"reject\w*",
    r"instead of",
    r"alternativ\w*",
    r"why not",
    r"won['’]t",
    r"will not",
    r"added (?:\w+ ){0,2}to the pep",
    r"out of scope",
    r"defer\w*",
    r"withdr[ae]w\w*",
    r"not going to",
)
# "-1" is a vote only when it is not part of a word or expression such as "n-1".
CUE_RE = re.compile(r"\b(?:" + "|".join(CUE_PHRASES) + r")\b|(?<![\w-])-1(?!\d)", re.IGNORECASE)


def cue_score(text: str) -> int:
    """Number of decision cues in ``text``."""
    return len(CUE_RE.findall(text or ""))


def assign_roles(thread: Thread) -> Thread:
    """Fill the role of every post whose role is "unknown"; returns the same thread."""
    if thread.kind == "discourse":
        _discourse_roles(thread)
    elif thread.kind in ("github_issue", "github_pr"):
        _github_roles(thread)
    else:
        _file_roles(thread)
    return thread


def _discourse_roles(thread: Thread) -> None:
    """Author > decider > maintainer > participant.

    Author comes first because a PEP author who sits on the Steering Council
    recuses from deciding their own PEP.
    """
    creators = _folded(thread.meta.get("created_by")) - NO_NAMES
    pep_authors = {_squash(name) for name in _as_list(thread.meta.get("pep_authors"))} - NO_NAMES
    for post in thread.posts:
        if post.role != "unknown":
            continue
        username = str(post.meta.get("username") or post.author).casefold()
        groups = f"{post.meta.get('primary_group_name') or ''} {post.meta.get('flair_name') or ''}".casefold()
        title = str(post.meta.get("user_title") or "").casefold()
        if username in creators or _squash(post.meta.get("name")) in pep_authors:
            post.role = "author"
        elif "steering" in groups or "steering" in title:
            post.role = "decider"
        elif "committers" in groups or "core dev" in title:
            post.role = "maintainer"
        else:
            post.role = "participant"


def _github_roles(thread: Thread) -> None:
    """Author > decider > maintainer > participant.

    The author is whoever opened the issue or pull request (meta ``opener``,
    else the writer of the first post by ``seq``), and stays the author even
    as an OWNER or MEMBER: opening, proposing and closing your own issue is
    not an independent decision. The decider is the member (OWNER, MEMBER or
    COLLABORATOR) who merged or closed it, other than the opener.
    """
    members = {
        post.author.casefold()
        for post in thread.posts
        if str(post.meta.get("author_association") or "").upper() in MEMBER_ASSOCIATIONS
    }
    closers = {_login(thread.meta.get("merged_by")), _login(thread.meta.get("closed_by"))} - {""}
    deciders = closers & members
    opener = _login(thread.meta.get("opener"))
    if not opener and thread.posts:
        opener = min(thread.posts, key=lambda post: post.seq).author.casefold()
    if opener in NO_NAMES:
        opener = None
    for post in thread.posts:
        if post.role != "unknown":
            continue
        login = post.author.casefold()
        if login == opener:
            post.role = "author"
        elif login in deciders:
            post.role = "decider"
        elif login in members:
            post.role = "maintainer"
        else:
            post.role = "participant"


def _file_roles(thread: Thread) -> None:
    """The thread's creator (meta ``created_by``, else the writer of the first post by ``seq``) is the author."""
    authors = _folded(thread.meta.get("created_by")) - NO_NAMES
    if not authors and thread.posts:
        authors = {min(thread.posts, key=lambda post: post.seq).author.casefold()} - NO_NAMES
    for post in thread.posts:
        if post.role == "unknown":
            post.role = "author" if post.author.casefold() in authors else "participant"


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _folded(value: Any) -> set[str]:
    """Case-folded names from a list or a single string."""
    return {str(item).casefold() for item in _as_list(value) if str(item).strip()}


def _squash(value: Any) -> str:
    """A display name with case and all whitespace ignored, for matching PEP authors."""
    return "".join(str(value or "").split()).casefold()


def _login(value: Any) -> str:
    """A GitHub login given as a string or as a user object with a ``login`` key."""
    if isinstance(value, dict):
        value = value.get("login")
    return str(value or "").casefold()
