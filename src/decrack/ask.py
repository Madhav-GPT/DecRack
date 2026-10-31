"""``decrack ask``: answer a question from one discussion, or from a repo's best-matching issues and PRs.

Shared by the ``ask`` command, ``decrack chat`` and the MCP ``ask`` tool. For a
bare repo URL it searches the repo's issues and PRs with the question's keywords
(GitHub search API), runs the top matches like ``decrack run`` (cached model calls
are reused) and ranks their decision records against the question. Otherwise it
runs the one discussion given. Every step goes through the preflight gates.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from decrack import preflight, search
from decrack.config import Settings
from decrack.models import DecisionRecord, Thread
from decrack.pipeline.roles import assign_roles
from decrack.sources import github as github_source
from decrack.store import Store

ASK_HELP = 'Tell DecRack what you want to know, e.g. decrack ask https://github.com/owner/repo "why not X?"'
# Words that carry no meaning in a GitHub search for a question.
QUESTION_STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have how i if in into is it its "
    "may might no not of on or our should so than that the their them then there these they this those to us "
    "was we were what when where which who why will with would you your".split()
)
MAX_KEYWORDS = 6


@dataclass
class AskResult:
    source: str
    question: str
    keywords: list[str]
    records: list[DecisionRecord]  # every thread read, in reading order
    ranked: list[tuple[DecisionRecord, str]]  # best match first, with why it matched ("" without a text match)


def question_keywords(question: str) -> list[str]:
    """The question's words minus stopwords, at most MAX_KEYWORDS, for the GitHub search API."""
    words: list[str] = []
    for word in re.findall(r"\w+", question.lower()):
        if len(word) > 1 and word not in QUESTION_STOPWORDS and word not in words:
            words.append(word)
    return words[:MAX_KEYWORDS]


def check_input(source: str, question: str) -> tuple[str, str] | None:
    """Gates before any work. Returns (owner, repo) for a bare repo URL, else None."""
    repo = github_source.parse_repo_url(source)
    if repo is not None and not question.strip():
        raise preflight.GateError(ASK_HELP, code=2)
    if repo is None:
        preflight.check_source(source)
    return repo


def run_ask(
    source: str,
    question: str,
    settings: Settings,
    store: Store,
    llm: Any,
    *,
    loader: Callable[..., Thread],
    compiler: Callable[..., DecisionRecord],
    client_factory: Callable[[], httpx.Client],
    max_threads: int = 3,
    progress: Callable[[str], None] | None = None,
) -> AskResult:
    """Read the source (or a repo's matching threads), compile each, and rank the records for the question.

    The caller has already passed the model gate. Raises ``preflight.GateError`` for every gate.
    """
    question = question.strip()
    repo = check_input(source, question)
    keywords = question_keywords(question) if repo is not None else []

    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    refs = [source]
    if repo is not None:
        owner, name = repo

        def search_repo(_ref: str, _settings: Settings) -> list[str]:
            with client_factory() as client:
                return github_source.search_threads(owner, name, keywords, client, max_threads)

        # The search goes through the fetch gate too: 404, rate limit and network errors read plainly.
        refs = preflight.fetch(source, settings, search_repo)
        if not refs:
            raise preflight.GateError(
                f"No issues or PRs in {owner}/{name} match: {' '.join(keywords)}.",
                "Try other words, or give an issue URL.",
                1,
            )

    records: list[DecisionRecord] = []
    for ref in refs:
        thread = assign_roles(preflight.fetch(ref, settings, loader))
        if not any(post.sentences for post in thread.posts):
            report(f"{thread.id}: nothing to analyze, skipped")
            continue
        store.save_thread(thread)
        report(f"Stored {thread.id}: {len(thread.posts)} posts — {thread.title}")
        record = compiler(thread, llm, settings, progress=progress)
        store.save_record(record)
        records.append(record)
    if not records:
        raise preflight.GateError(preflight.NOTHING_TO_ANALYZE, code=0)

    # Records the question matches come first; every record read is part of the answer.
    hits = search.why(store, question, limit=50) if question else []
    ids = [record.id for record in records]
    why_of = {hit.record.id: hit.why for hit in hits if hit.record.id in ids}
    ordered = sorted(records, key=lambda record: (record.id not in why_of, ids.index(record.id)))
    return AskResult(source, question, keywords, records, [(record, why_of.get(record.id, "")) for record in ordered])
