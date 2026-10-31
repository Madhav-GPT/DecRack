"""Shared test data: a small PEP-style thread and a hand-built record for it (revision 2 contracts).

The thread is written so that every post's text is its sentences joined by
single spaces, which keeps the spans easy to compute here without importing
the text module. The record is built by hand (not by the pipeline) so store,
export, verify and CLI tests do not depend on extraction.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from decrack.models import (
    AliasTarget,
    CodeLink,
    DecidedBy,
    DecisionRecord,
    Evidence,
    Option,
    Post,
    Reason,
    RunInfo,
    SourceRef,
    Span,
    StatusEvent,
    Thread,
    make_record_id,
    sentence_alias,
)

TOPIC_ID = 99999
THREAD_URL = "https://discuss.python.org/t/pep-9999-lazy-widgets/99999"

POSTS = [
    (
        "alice",
        "author",
        [
            "I propose PEP 9999 to add lazy widgets to the standard library.",
            "Widgets would be created on first access with a new lazy keyword.",
            "Please share feedback on the design.",
        ],
    ),
    (
        "bob",
        "participant",
        [
            "Why not use a decorator instead of a new keyword?",
            "A decorator would avoid adding new syntax.",
        ],
    ),
    (
        "carol",
        "participant",
        [
            "I object to the hard keyword.",
            "It breaks existing code that uses lazy as a name.",
        ],
    ),
    (
        "dave",
        "maintainer",
        [
            "A global flag to enable laziness everywhere would be simpler.",
            "It could be switched on with a command line option.",
        ],
    ),
    (
        "alice",
        "author",
        [
            "Thanks for all the ideas.",
            "We rejected the decorator approach because decorators cannot apply to import statements.",
            "The global flag is also rejected since it changes behaviour for every library at once.",
        ],
    ),
    (
        "erin",
        "participant",
        [
            "The global flag would break libraries that rely on import side effects.",
            "I agree it should not be added.",
        ],
    ),
    (
        "frank",
        "participant",
        [
            "Another option is a soft keyword.",
            "A soft keyword keeps lazy usable as a normal name.",
        ],
    ),
    (
        "sam",
        "decider",
        [
            "The Steering Council accepts PEP 9999 with the soft keyword.",
            "The hard keyword is rejected because it breaks existing code.",
        ],
    ),
]


def post_id(seq: int) -> str:
    return f"dpo:{TOPIC_ID}:{1000 + seq}"


def spans_for(sentences: list[str]) -> list[Span]:
    spans, position = [], 0
    for index, sentence in enumerate(sentences, start=1):
        spans.append(Span(index=index, start=position, end=position + len(sentence)))
        position += len(sentence) + 1  # the single space that joins sentences
    return spans


def make_synthetic_thread() -> Thread:
    posts = []
    for seq, (author, role, sentences) in enumerate(POSTS, start=1):
        text = " ".join(sentences)
        meta: dict = {"topic_id": TOPIC_ID, "post_number": seq, "username": author}
        if role == "decider":
            meta.update({"flair_name": "steering-council", "user_title": "Steering Council member"})
        if role == "maintainer":
            meta.update({"primary_group_name": "committers", "user_title": "CPython core developer"})
        posts.append(
            Post(
                id=post_id(seq),
                source_id=f"dpo:t{TOPIC_ID}",
                source_post_number=seq,
                seq=seq,
                version=1,
                author=author,
                role=role,
                created_at=datetime(2026, 1, seq, 10, 0, tzinfo=timezone.utc),
                reply_to=post_id(1) if seq > 1 else None,
                url=f"{THREAD_URL}/{seq}",
                text=text,
                sentences=list(sentences),
                spans=spans_for(sentences),
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                meta=meta,
            )
        )
    return Thread(
        id="pep:9999",
        kind="discourse",
        url=THREAD_URL,
        title="PEP 9999: Lazy widgets",
        posts=posts,
        meta={"created_by": ["alice"], "topic_ids": [TOPIC_ID], "forum": "https://discuss.python.org", "pep": 9999},
    )


def evidence(thread: Thread, seq: int, indexes: list[int], evidence_type: str = "other") -> Evidence:
    """Evidence for a contiguous run of sentences of the post at ``seq``, quote sliced from its text."""
    post = thread.posts[seq - 1]
    start, end = post.spans[indexes[0] - 1].start, post.spans[indexes[-1] - 1].end
    return Evidence(
        post_id=post.id,
        post_version=post.version,
        post_sha256=post.sha256,
        sentence_indexes=list(indexes),
        start=start,
        end=end,
        quote=post.text[start:end],
        url=post.url,
        author=post.author,
        source_check="valid",
        support="supported",
        evidence_type=evidence_type,
    )


def event(thread: Thread, seq: int, act: str, evidence_type: str, indexes: list[int], status_after: str) -> StatusEvent:
    post = thread.posts[seq - 1]
    return StatusEvent(
        post_id=post.id,
        act=act,
        role=post.role,
        author=post.author,
        evidence_type=evidence_type,
        evidence=[evidence(thread, seq, indexes, evidence_type)],
        support="supported",
        status_after=status_after,
    )


def make_sample_record(thread: Thread) -> DecisionRecord:
    ev, act = (lambda *a: evidence(thread, *a)), (lambda *a: event(thread, *a))  # noqa: E731
    alice, sam = DecidedBy(handle="alice", role="author"), DecidedBy(handle="sam", role="decider")
    options = [
        Option(
            key="A1",
            title="Use a decorator instead of a new keyword",
            summary="Mark lazy objects with a decorator rather than new syntax.",
            status="rejected",
            status_kind="confirmed",
            status_basis="author_statement",
            status_post=post_id(5),
            decided_by=alice,
            status_history=[
                act(2, "propose", "proposal", [1], "proposed"),
                act(5, "reject", "decision_statement", [2], "rejected"),
            ],
            reasons=[
                Reason(
                    stance="con",
                    text="Decorators cannot apply to import statements.",
                    evidence=[ev(5, [2], "decision_statement")],
                    support="supported",
                )
            ],
            evidence=[ev(2, [1], "proposal"), ev(5, [2], "decision_statement")],
            confidence="high",
        ),
        Option(
            key="A2",
            title="Global flag to enable laziness everywhere",
            summary="One switch that makes every import lazy.",
            status="rejected",
            status_kind="confirmed",
            status_basis="author_statement",
            status_post=post_id(5),
            decided_by=alice,
            status_history=[
                act(4, "propose", "proposal", [1], "proposed"),
                act(5, "reject", "decision_statement", [3], "rejected"),
                act(6, "object", "objection", [1], "rejected"),
            ],
            reasons=[
                Reason(
                    stance="con",
                    text="It changes behaviour for every library at once.",
                    evidence=[ev(5, [3], "decision_statement")],
                    support="supported",
                ),
                Reason(
                    stance="con",
                    text="It would break libraries that rely on import side effects.",
                    evidence=[ev(6, [1], "objection")],
                    support="supported",
                ),
            ],
            evidence=[ev(4, [1], "proposal"), ev(5, [3], "decision_statement"), ev(6, [1], "objection")],
            confidence="high",
        ),
        Option(
            key="A3",
            title="Soft keyword",
            summary="A keyword that stays usable as a normal name.",
            status="accepted",
            status_kind="confirmed",
            status_basis="decider_statement",
            status_post=post_id(8),
            decided_by=sam,
            status_history=[
                act(7, "propose", "proposal", [1], "proposed"),
                act(8, "accept", "decision_statement", [1], "accepted"),
            ],
            reasons=[
                Reason(
                    stance="pro",
                    text="It keeps lazy usable as a normal name.",
                    evidence=[ev(7, [2], "support")],
                    support="supported",
                )
            ],
            evidence=[ev(7, [1], "proposal"), ev(8, [1], "decision_statement")],
            confidence="high",
        ),
        Option(
            key="A4",
            title="Hard lazy keyword",
            summary="A new reserved keyword lazy.",
            status="rejected",
            status_kind="confirmed",
            status_basis="decider_statement",
            status_post=post_id(8),
            decided_by=sam,
            status_history=[
                act(1, "propose", "proposal", [2], "proposed"),
                act(3, "object", "objection", [1], "unresolved"),
                act(8, "reject", "decision_statement", [2], "rejected"),
            ],
            reasons=[
                Reason(
                    stance="con",
                    text="It breaks existing code that uses lazy as a name.",
                    evidence=[ev(3, [2], "objection"), ev(8, [2], "decision_statement")],
                    support="supported",
                )
            ],
            evidence=[ev(1, [2], "proposal"), ev(3, [1, 2], "objection"), ev(8, [2], "decision_statement")],
            confidence="high",
        ),
    ]
    alias_map = {
        sentence_alias(post.seq, span.index): AliasTarget(post_id=post.id, version=post.version, index=span.index)
        for post in thread.posts
        for span in post.spans
    }
    return DecisionRecord(
        id=make_record_id(thread.id),
        thread_id=thread.id,
        thread_url=thread.url,
        question=thread.title,
        outcome="4 options: 1 accepted, 3 rejected",
        options=options,
        decided_by=sam,
        decided_in_post=post_id(8),
        code_links=[
            CodeLink(repo="example/widgets", path="Lib/widgets.py", method="mentioned", strength="direct"),
            CodeLink(repo="example/widgets", path="Lib/lazy.py", pr=42, method="pr_files", strength="historical"),
        ],
        verification="machine_checked",
        run=RunInfo(
            mode="scripted",
            decrack_version="0.1.0",
            model="scripted",
            params={"num_ctx": 32768, "temperature": 0, "think": False},
            prompt_version="test",
            started_at=datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc),
            seconds=1.0,
            llm_calls=4,
            windows=1,
            candidates_total=10,
            candidates_verified=10,
            support_checked=True,
            alias_map=alias_map,
            source_allowlist=[SourceRef(post_id=p.id, version=p.version, sha256=p.sha256) for p in thread.posts],
        ),
    )


@pytest.fixture
def synthetic_thread() -> Thread:
    return make_synthetic_thread()


@pytest.fixture
def sample_record(synthetic_thread: Thread) -> DecisionRecord:
    return make_sample_record(synthetic_thread)


@pytest.fixture
def store(tmp_path):
    from decrack.store import Store

    db = Store(tmp_path / "decrack.db")
    yield db
    db.close()
