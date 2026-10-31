"""Shared data contracts for DecRack (revision 2).

Every module builds against these Pydantic models. Acquire produces a
``Thread`` of ``Post`` objects, Compile turns it into a ``DecisionRecord``,
and Serve reads records back out of SQLite.

Identity is stable and source-native: a post is ``dpo:{topic}:{post_id}``,
``gh:{owner}/{repo}#{n}:c{comment_id}`` or ``file:{sha8}:{n}``, and a cited
sentence is (post id, post version, sentence index) plus character offsets.
The model only ever sees short per-run aliases such as ``p12.s3`` (12 is the
post's ``seq`` in the merged thread). ``RunInfo.alias_map`` records what each
alias meant, and the gate resolves aliases at once: nothing downstream stores
an alias.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["author", "decider", "maintainer", "participant", "unknown"]
ThreadKind = Literal["discourse", "github_issue", "github_pr", "file"]
Act = Literal["propose", "support", "object", "accept", "reject", "defer", "withdraw"]
EvidenceType = Literal["decision_statement", "author_position", "objection", "support", "proposal", "other"]
Status = Literal["proposed", "accepted", "rejected", "withdrawn", "deferred", "superseded", "unresolved"]
StatusKind = Literal["confirmed", "inferred", "contested", "unresolved"]
Basis = Literal["decider_statement", "author_statement", "participant_consensus", "none"]
Confidence = Literal["high", "medium", "low"]
SourceCheck = Literal["valid", "not_found", "source_changed"]
Support = Literal["supported", "partial", "unsupported", "unchecked"]
Stance = Literal["pro", "con"]
Verification = Literal["unverified", "machine_checked", "human_confirmed", "disputed"]
LinkMethod = Literal["mentioned", "pr_files", "blame", "rename_follow", "search"]
LinkStrength = Literal["direct", "historical", "suggested"]
RunMode = Literal["live", "replay", "scripted"]

ROLES: tuple[str, ...] = ("author", "decider", "maintainer", "participant", "unknown")
ACTS: tuple[str, ...] = ("propose", "support", "object", "accept", "reject", "defer", "withdraw")
EVIDENCE_TYPES: tuple[str, ...] = (
    "decision_statement",
    "author_position",
    "objection",
    "support",
    "proposal",
    "other",
)
STATUSES: tuple[str, ...] = (
    "accepted",
    "rejected",
    "withdrawn",
    "deferred",
    "superseded",
    "unresolved",
    "proposed",
)
STATUS_KINDS: tuple[str, ...] = ("confirmed", "inferred", "contested", "unresolved")

ALIAS_RE = re.compile(r"^p(\d+)\.s(\d+)$")

SCHEMA_VERSION = "decrack-record/0.2"


def sentence_alias(seq: int, index: int) -> str:
    """The prompt alias of sentence ``index`` (1-based) in the post at ``seq``, e.g. ``p12.s3``."""
    return f"p{seq}.s{index}"


def parse_alias(value: str) -> tuple[int, int] | None:
    """Split ``"p12.s3"`` into ``(12, 3)``; return None if it is malformed."""
    match = ALIAS_RE.match(value.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def make_record_id(thread_id: str) -> str:
    """Deterministic decision-record ID for a thread, e.g. ``dr-1a2b3c4d``."""
    return "dr-" + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:8]


class Span(BaseModel):
    """One sentence of a post: ``text[start:end]``, with a 1-based index."""

    index: int
    start: int
    end: int


class Post(BaseModel):
    """One message of a discussion. ``id`` is stable; ``seq`` is only its place in this merged thread."""

    id: str  # "dpo:106942:123456", "gh:python/cpython#12345:c987", "file:1a2b3c4d:3"
    source_id: str = ""  # the topic, issue or file: "dpo:t106942", "gh:python/cpython#12345", "file:1a2b3c4d"
    source_post_number: int | None = None  # native number inside its source (Discourse post_number)
    seq: int  # 1-based position in the merged thread; display and prompt aliases only
    version: int = 1  # Discourse post version, else 1
    author: str
    role: Role = "unknown"
    created_at: datetime | None = None  # timezone-aware UTC when known
    reply_to: str | None = None  # id of the post this one replies to
    quotes: list[str] = Field(default_factory=list)  # ids of the posts it quotes
    url: str = ""
    text: str = ""  # NFC-normalized own text: quote blocks removed, code blocks kept
    sentences: list[str] = Field(default_factory=list)  # sentences[i - 1] == text[spans[i - 1].start:spans[i - 1].end]
    spans: list[Span] = Field(default_factory=list)
    sha256: str = ""  # sha256 of ``text`` (already NFC)
    meta: dict[str, Any] = Field(default_factory=dict)


class Thread(BaseModel):
    """A whole discussion: one topic, several merged topics, an issue/PR or a file."""

    id: str  # "dpo:t106942", "pep:830", "gh:python/cpython#12345", "file:notes"
    kind: ThreadKind
    url: str = ""
    title: str = ""
    posts: list[Post] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def post_by_id(self, post_id: str) -> Post | None:
        for post in self.posts:
            if post.id == post_id:
                return post
        return None

    def post_by_seq(self, seq: int) -> Post | None:
        for post in self.posts:
            if post.seq == seq:
                return post
        return None


class Candidate(BaseModel):
    """One item of MAP output. Kept flat and small so a 1.5B model can fill it reliably.

    The evidence type is not asked of the model: code derives it from the act,
    the poster's role and decision cues in the cited sentences.
    """

    alt_ref: str = Field(description='"A3" for a known alternative, or "new" for one not in the list')
    alternative: str = Field(
        description="Short name of the alternative, at most 12 words",
        json_schema_extra={"maxLength": 100},  # grammar bound for Ollama; not validated
    )
    act: Act = Field(description="What the cited sentences do to this alternative")
    reason: str | None = Field(description="The reason given, in at most one sentence; null if none")
    cites: list[str] = Field(
        description='Sentence IDs that show this act, such as "p12.s3"',
        json_schema_extra={"maxItems": 6},  # grammar bound for Ollama; not validated
    )


class MapOutput(BaseModel):
    # maxItems goes into the JSON schema Ollama turns into a grammar, so a small model that starts
    # repeating items must close the array. Pydantic does not enforce it.
    items: list[Candidate] = Field(default_factory=list, json_schema_extra={"maxItems": 20})


class Evidence(BaseModel):
    """A verbatim quote: ``quote == text[start:end]`` of one post version, cut at sentence boundaries."""

    post_id: str
    post_version: int = 1
    post_sha256: str = ""
    sentence_indexes: list[int]  # 1-based, one contiguous run
    start: int
    end: int
    quote: str
    url: str = ""
    author: str = ""
    source_check: SourceCheck = "valid"
    support: Support = "unchecked"
    evidence_type: EvidenceType = "other"


class Reason(BaseModel):
    stance: Stance
    text: str
    evidence: list[Evidence] = Field(default_factory=list)
    support: Support = "unchecked"


class StatusEvent(BaseModel):
    """One act on an option, with its evidence and the status after it."""

    post_id: str
    act: Act
    role: Role
    author: str = ""
    evidence_type: EvidenceType = "other"
    evidence: list[Evidence] = Field(default_factory=list)
    support: Support = "unchecked"
    status_after: Status


class DecidedBy(BaseModel):
    handle: str
    role: Role


class Option(BaseModel):
    """One alternative considered in the discussion."""

    key: str  # "A1", "A2", ...
    title: str
    summary: str = ""  # one line, shown to the model as context in later windows
    status: Status = "proposed"
    status_kind: StatusKind = "unresolved"
    status_basis: Basis = "none"
    status_post: str | None = None  # id of the post whose statement set the status
    decided_by: DecidedBy | None = None
    status_note: str = ""  # e.g. "inferred from objections by 2 participants"
    status_history: list[StatusEvent] = Field(default_factory=list)
    reasons: list[Reason] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: Confidence = "low"


class CodeLink(BaseModel):
    repo: str = ""  # "owner/name" when known
    path: str
    commit: str | None = None
    pr: int | None = None
    method: LinkMethod
    strength: LinkStrength  # direct: the thread names it; historical: git facts; suggested: search


class AliasTarget(BaseModel):
    """What a prompt alias such as ``p12.s3`` pointed at during one run."""

    post_id: str
    version: int
    index: int


class SourceRef(BaseModel):
    """One post version that was shown to the model."""

    post_id: str
    version: int
    sha256: str


class RunInfo(BaseModel):
    """How a record was produced; written as ``run.json`` next to real-run examples."""

    mode: RunMode = "live"
    decrack_version: str
    model: str
    model_digest: str = ""
    ollama_version: str = ""
    params: dict[str, Any] = Field(default_factory=dict)  # num_ctx, temperature, think, window sizes, ...
    prompt_version: str
    schema_version: str = SCHEMA_VERSION
    started_at: datetime
    seconds: float = 0.0
    llm_calls: int = 0
    cache_hits: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    windows: int = 0
    candidates_total: int = 0
    candidates_verified: int = 0
    support_checked: bool = False
    alias_map: dict[str, AliasTarget] = Field(default_factory=dict)
    source_allowlist: list[SourceRef] = Field(default_factory=list)


class DecisionRecord(BaseModel):
    """Everything DecRack recovered from one thread."""

    id: str  # make_record_id(thread_id)
    thread_id: str
    thread_url: str = ""
    question: str
    outcome: str
    options: list[Option] = Field(default_factory=list)
    decided_by: DecidedBy | None = None
    decided_in_post: str | None = None  # post id
    code_links: list[CodeLink] = Field(default_factory=list)
    verification: Verification = "unverified"
    run: RunInfo | None = None


class GoldItem(BaseModel):
    """One "Rejected Ideas" entry from a PEP, written by hand for the evaluation."""

    id: str
    idea: str
    summary: str = ""  # optional first paragraph that introduces the idea
    reason: str = ""
    recoverable: bool | None = None  # discussed in the supplied thread? None = not checked


class GoldFile(BaseModel):
    """``eval/gold/pep-NNNN.json``."""

    pep: int
    title: str = ""
    topics: list[str] = Field(default_factory=list)
    python_peps_commit: str = ""
    leak_flags: list[str] = Field(default_factory=list)
    items: list[GoldItem] = Field(default_factory=list)
