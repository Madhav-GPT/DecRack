"""Consolidate: stable keys for alternatives, merging, status rules, reasons and confidence.

Everything here is code except two optional model calls: one ``merge`` call
per thread ("which of these name the same idea?") and one ``refine_reasons``
call per decided option. Status, status kind and confidence never come from
the model: ``decide`` derives them from the option's status events, their
evidence type, the writer's role and the semantic support verdicts that
``support.check_support`` adds (the conservative status model, R2.4).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from pydantic import ValidationError

from decrack.models import STATUSES, DecidedBy, Evidence, Option, Post, Reason, StatusEvent, Thread
from decrack.pipeline.gate import GatedCandidate, build_aliases, evidence_for, resolve_aliases, split_cites
from decrack.pipeline.llm import LLMOutputError
from decrack.pipeline.prompts import MergeOutput, RefineOutput, merge_messages, refine_messages, render_post
from decrack.text import estimate_tokens

if TYPE_CHECKING:  # only a type hint here
    from decrack.pipeline.llm import LLM

log = logging.getLogger(__name__)

TITLE_SIMILARITY = 0.85
REASON_SIMILARITY = 0.9
MAX_TITLE_WORDS = 12
MAX_SUMMARY_WORDS = 20

ACT_STATUS = {
    "accept": "accepted",
    "reject": "rejected",
    "object": "rejected",
    "defer": "deferred",
    "withdraw": "withdrawn",
}
CON_ACTS = {"object", "reject", "withdraw", "defer"}
DECIDED_STATUSES = ("accepted", "rejected", "withdrawn", "deferred")
PUNCTUATION_RE = re.compile(r"[^\w\s]")

# Status rules (R2.4). Authority: decider 3 > author 2 > everyone else 1.
AUTHORITY = {"decider": 3, "author": 2}
AUTHORITATIVE_ROLES = ("decider", "author")
STATEMENT_ACTS = ("accept", "reject", "defer", "withdraw")  # with evidence_type "decision_statement"
AUTHOR_NEGATIVE_ACTS = ("object", "reject", "defer", "withdraw")
BACKING_ACTS = ("propose", "support", "accept")
OBJECTION_ACTS = ("object", "reject")
# The way an act or a status points, used to tell whether a later act contradicts a status.
ACT_DIRECTION = {
    "propose": "for",
    "support": "for",
    "accept": "for",
    "object": "against",
    "reject": "against",
    "withdraw": "against",
    "defer": "not now",
}
STATUS_DIRECTION = {"accepted": "for", "rejected": "against", "withdrawn": "against", "deferred": "not now"}


def normalize_text(text: str) -> str:
    """Lowercase, punctuation as spaces, single spaces: the form difflib compares."""
    return " ".join(PUNCTUATION_RE.sub(" ", text.casefold()).split())


def similarity(first: str, second: str) -> float:
    """difflib ratio of two strings, the same whichever is passed first."""
    a, b = sorted((first, second))
    return SequenceMatcher(None, a, b).ratio()


def short_title(text: str) -> str:
    return " ".join(text.split()[:MAX_TITLE_WORDS])


def short_summary(text: str) -> str:
    """One line of at most MAX_SUMMARY_WORDS words."""
    return " ".join(text.split()[:MAX_SUMMARY_WORDS])


def key_number(key: str) -> int:
    return int(key[1:])


class AltRegistry:
    """Assigns keys A1, A2, ... to alternatives while windows are processed in order.

    A valid known key from the model keeps its key. A "new" or unknown key joins
    the existing alternative whose normalised title is at least 85% similar
    (difflib), or gets the next key with the alternative's name, cut to 12
    words, as its title. Each key keeps a one-line summary: the first non-empty
    reason filed under it, cut to 20 words.
    """

    def __init__(self) -> None:
        self.titles: dict[str, str] = {}
        self.summaries: dict[str, str] = {}
        self.normalized: dict[str, str] = {}
        self.members: dict[str, list[tuple[int, GatedCandidate]]] = {}
        self._count = 0

    def known(self) -> list[tuple[str, str, str]]:
        """``(key, title, summary)`` for every alternative, to show the model in the next MAP call."""
        return [(key, title, self.summaries[key]) for key, title in self.titles.items()]

    def assign(self, item: GatedCandidate) -> str | None:
        """File ``item`` under a key and return the key; None when it has no known key and no name."""
        ref = item.candidate.alt_ref.strip().upper()
        if ref in self.titles:
            key = ref
        else:
            title = short_title(item.candidate.alternative)
            normalized = normalize_text(title)
            if not normalized:
                return None
            key = self.find(normalized)
            if key is None:
                key = f"A{len(self.titles) + 1}"
                self.titles[key] = title
                self.summaries[key] = ""
                self.normalized[key] = normalized
                self.members[key] = []
        if not self.summaries[key]:
            self.summaries[key] = short_summary(item.candidate.reason)
        self.members[key].append((self._count, item))
        self._count += 1
        return key

    def find(self, normalized: str) -> str | None:
        """The key whose title is most similar to ``normalized``, when at least TITLE_SIMILARITY."""
        best_key, best_score = None, 0.0
        for key, title in self.normalized.items():
            score = similarity(normalized, title)
            if score >= TITLE_SIMILARITY and score > best_score:
                best_key, best_score = key, score
        return best_key


def consolidate(thread: Thread, gated: list[GatedCandidate], llm: LLM | None = None) -> list[Option]:
    """Turn the gated candidates of ``thread`` (in window order) into options with a preliminary status.

    Keys come from replaying AltRegistry over ``gated`` in order, which gives
    the same keys ``run`` showed the model window by window. With an ``llm``,
    one ``merge`` call joins alternatives that name the same idea. Options are
    numbered A1, A2, ... again after merging. Every option goes through
    ``decide``; its events and reasons are still "unchecked" at this point.
    """
    registry = AltRegistry()
    for item in gated:
        registry.assign(item)
    order = {post.id: post.seq for post in thread.posts}
    return [
        _build_option(f"A{number}", title, summary, items, order)
        for number, (title, summary, items) in enumerate(_merged_groups(registry, llm), start=1)
    ]


def _ask_merge(registry: AltRegistry, llm: LLM) -> list[list[str]]:
    """Groups from the ``merge`` call, kept only when they name known keys, each key at most once."""
    try:
        data = llm.complete_json("merge", merge_messages(registry.known()), MergeOutput, think=False)
        groups = MergeOutput.model_validate(data).groups
    except (LLMOutputError, ValidationError) as exc:
        log.warning("merge step skipped: %s", exc)
        return []
    used: set[str] = set()
    valid: list[list[str]] = []
    for group in groups:
        keys: list[str] = []
        for raw in group:
            key = str(raw).strip().upper()
            if key in registry.titles and key not in used and key not in keys:
                keys.append(key)
        if len(keys) >= 2:
            valid.append(keys)
            used.update(keys)
    return valid


def _merged_groups(registry: AltRegistry, llm: LLM | None) -> list[tuple[str, str, list[GatedCandidate]]]:
    """``(title, summary, members in thread order)`` per alternative, after merging duplicates into the lowest key.

    The title is the lowest key's; the summary is the first non-empty summary
    of the merged keys, lowest key first.
    """
    parent = {key: key for key in registry.titles}

    def root(key: str) -> str:
        while parent[key] != key:
            key = parent[key]
        return key

    def join(first: str, second: str) -> None:
        low, high = sorted((root(first), root(second)), key=key_number)
        parent[high] = low

    if llm is not None and len(registry.titles) >= 2:
        for group in _ask_merge(registry, llm):
            for key in group[1:]:
                join(group[0], key)

    roots = sorted({root(key) for key in parent}, key=key_number)
    for index, first in enumerate(roots):
        for second in roots[index + 1 :]:
            close = similarity(registry.normalized[first], registry.normalized[second]) >= TITLE_SIMILARITY
            if close and root(first) != root(second):
                join(first, second)

    keys_by_root: dict[str, list[str]] = {}
    for key in sorted(parent, key=key_number):
        keys_by_root.setdefault(root(key), []).append(key)
    result = []
    for top in sorted(keys_by_root, key=key_number):
        keys = keys_by_root[top]
        members = sorted(
            (pair for key in keys for pair in registry.members[key]), key=lambda pair: (pair[1].post.seq, pair[0])
        )
        summary = next((registry.summaries[key] for key in keys if registry.summaries[key]), "")
        result.append((registry.titles[top], summary, [item for _, item in members]))
    return result


def _copies(evidence: list[Evidence]) -> list[Evidence]:
    """Own copies, so a support verdict set on one claim's evidence never changes another claim's."""
    return [item.model_copy(deep=True) for item in evidence]


def _events(items: list[GatedCandidate], order: dict[str, int]) -> list[StatusEvent]:
    """One event per (act, post) in thread order; a repeat (overlapping windows) only adds its evidence."""
    events: dict[tuple[str, str], StatusEvent] = {}
    for item in items:
        mark = (item.candidate.act, item.post.id)
        if mark in events:
            events[mark].evidence = merge_evidence(events[mark].evidence + _copies(item.evidence), order)
            continue
        events[mark] = StatusEvent(
            post_id=item.post.id,
            act=item.candidate.act,
            role=item.role,
            author=item.author,
            evidence_type=item.evidence_type,
            evidence=merge_evidence(_copies(item.evidence), order),
            support="unchecked",
            status_after="proposed",  # decide() sets the real value
        )
    return list(events.values())


def _build_option(key: str, title: str, summary: str, items: list[GatedCandidate], order: dict[str, int]) -> Option:
    events = _events(items, order)
    reasons: list[Reason] = []
    for item in items:
        text = " ".join(item.candidate.reason.split())
        if text:
            stance = "con" if item.candidate.act in CON_ACTS else "pro"
            add_reason(reasons, Reason(stance=stance, text=text, evidence=_copies(item.evidence)), order)
    # The option's evidence is the union of its claims' evidence. Each entry is the object of the first
    # claim that cites it (events before reasons), so it shows that claim's support verdict.
    cited = [evidence for event in events for evidence in event.evidence]
    cited += [evidence for reason in reasons for evidence in reason.evidence]
    option = Option(
        key=key,
        title=title,
        summary=summary,
        status_history=events,
        reasons=reasons,
        evidence=merge_evidence(cited, order),
    )
    decide(option)
    return option


def add_reason(reasons: list[Reason], new: Reason, order: dict[str, int]) -> None:
    """Append ``new``, or merge its evidence into a near-identical reason (difflib >= 0.9) with the same stance."""
    normalized = normalize_text(new.text)
    if not normalized:
        return
    for reason in reasons:
        if reason.stance == new.stance and similarity(normalized, normalize_text(reason.text)) >= REASON_SIMILARITY:
            reason.evidence = merge_evidence(reason.evidence + new.evidence, order)
            return
    reasons.append(new)


def merge_evidence(items: list[Evidence], order: dict[str, int]) -> list[Evidence]:
    """Evidence without repeats of (post_id, sentence_indexes), in thread order.

    ``order`` maps post id -> seq. The first object of each repeat is kept.
    """
    unique: dict[tuple[str, tuple[int, ...]], Evidence] = {}
    for evidence in items:
        unique.setdefault((evidence.post_id, tuple(evidence.sentence_indexes)), evidence)
    unknown = len(order) + 1  # never happens for evidence of this thread; sorts last

    def place(evidence: Evidence) -> tuple[int, int, int]:
        first = evidence.sentence_indexes[0] if evidence.sentence_indexes else 0
        return order.get(evidence.post_id, unknown), first, len(evidence.sentence_indexes)

    return sorted(unique.values(), key=place)


# Status rules


@dataclass
class Ruling:
    """What the status rules make of a list of events."""

    status: str
    kind: str
    basis: str
    event: StatusEvent | None = None  # sets status_post and decided_by
    grounds: list[StatusEvent] = field(default_factory=list)  # the events the status rests on
    note: str = ""


def authority(role: str) -> int:
    return AUTHORITY.get(role, 1)


def is_statement(event: StatusEvent) -> bool:
    """An authoritative decision statement: an author or decider accepts, rejects, defers or withdraws."""
    return (
        event.role in AUTHORITATIVE_ROLES
        and event.act in STATEMENT_ACTS
        and event.evidence_type == "decision_statement"
    )


def _from_statements(events: list[StatusEvent]) -> Ruling | None:
    """Rule 1: authoritative decision statements, walked in thread order.

    A later statement takes over when its authority is at least the current
    one's (it supersedes a different status, or restates the same one), so the
    status comes from the latest statement of the highest authority that made
    one. The option is contested when a later author or decider event disagrees
    with it: a lower-authority statement with a different status, or any other
    act that points another way (for, against or not now).
    """
    current: int | None = None
    for index, event in enumerate(events):
        if is_statement(event) and (current is None or authority(event.role) >= authority(events[current].role)):
            current = index
    if current is None:
        return None
    event = events[current]
    status = ACT_STATUS[event.act]

    def disagrees(later: StatusEvent) -> bool:
        if later.role not in AUTHORITATIVE_ROLES:
            return False
        if is_statement(later):
            return ACT_STATUS[later.act] != status
        return ACT_DIRECTION[later.act] != STATUS_DIRECTION[status]

    if any(disagrees(later) for later in events[current + 1 :]):
        kind = "contested"
    elif event.support == "supported":
        kind = "confirmed"
    else:
        kind = "inferred"
    basis = "decider_statement" if event.role == "decider" else "author_statement"
    return Ruling(status, kind, basis, event, [event])


def _from_author(events: list[StatusEvent]) -> Ruling | None:
    """Rule 2: the latest author object/reject/defer/withdraw (any evidence type) not followed by backing."""
    latest = None
    for index, event in enumerate(events):
        if event.role == "author" and event.act in AUTHOR_NEGATIVE_ACTS:
            latest = index
    if latest is None:
        return None
    backed = any(
        later.role in AUTHORITATIVE_ROLES and later.act in BACKING_ACTS for later in events[latest + 1 :]
    )
    if backed:
        return None
    event = events[latest]
    return Ruling(ACT_STATUS[event.act], "inferred", "author_statement", event, [event])


def _from_consensus(events: list[StatusEvent]) -> Ruling | None:
    """Rule 3: objections from at least 2 people who are neither author nor decider, and no backing from them."""
    if any(event.role in AUTHORITATIVE_ROLES and event.act in BACKING_ACTS for event in events):
        return None
    objections = [
        event for event in events if event.act in OBJECTION_ACTS and event.role not in AUTHORITATIVE_ROLES
    ]
    people = {event.author.casefold() for event in objections}
    if len(people) < 2:
        return None
    note = f"inferred from objections by {len(people)} participants (weaker)"
    return Ruling("rejected", "inferred", "participant_consensus", objections[-1], objections, note)


def status_ruling(events: list[StatusEvent]) -> Ruling:
    """Apply the status rules to ``events`` (in thread order), ignoring events whose support is "unsupported"."""
    counted = [event for event in events if event.support != "unsupported"]
    ruling = _from_statements(counted) or _from_author(counted) or _from_consensus(counted)
    if ruling is not None:
        return ruling
    # Rule 4: nothing decided. "proposed" when every counted event is a proposal.
    only_proposals = bool(counted) and all(event.act == "propose" for event in counted)
    return Ruling("proposed" if only_proposals else "unresolved", "unresolved", "none")


def _confidence(ruling: Ruling) -> str:
    """confirmed + supported -> high; inferred + every event it rests on supported -> medium; else low."""
    supported = bool(ruling.grounds) and all(event.support == "supported" for event in ruling.grounds)
    if supported and ruling.kind == "confirmed":
        return "high"
    if supported and ruling.kind == "inferred":
        return "medium"
    return "low"


def decide(option: Option) -> None:
    """Recompute the option's status fields, each event's ``status_after`` and the confidence from its events.

    ``option.status_history`` must be in thread order (``consolidate`` builds it
    so). Rules, first match wins (events with support "unsupported" are ignored):

    1. Authoritative decision statements (see ``_from_statements``): basis
       decider_statement or author_statement; kind confirmed when the deciding
       statement's support is "supported", inferred otherwise, or contested.
    2. The author's latest objection, rejection, deferral or withdrawal that
       no author or decider backed afterwards: inferred, author_statement.
    3. Objections from at least 2 other people with no author or decider
       backing: rejected, inferred, participant_consensus, with a note.
    4. Otherwise unresolved (proposed when there are only proposals).
    """
    events = option.status_history
    for index, event in enumerate(events):
        event.status_after = status_ruling(events[: index + 1]).status
    ruling = status_ruling(events)
    option.status = ruling.status
    option.status_kind = ruling.kind
    option.status_basis = ruling.basis
    option.status_post = ruling.event.post_id if ruling.event is not None else None
    if ruling.event is not None and ruling.basis in ("decider_statement", "author_statement"):
        option.decided_by = DecidedBy(handle=ruling.event.author, role=ruling.event.role)
    else:
        option.decided_by = None
    option.status_note = ruling.note
    option.confidence = _confidence(ruling)


def rate_confidence(option: Option) -> str:
    """high, medium or low, derived from the option's events and their support (the same rule ``decide`` uses)."""
    return _confidence(status_ruling(option.status_history))


def summarize_outcome(options: list[Option]) -> str:
    """For example "12 options: 1 accepted, 8 rejected, 3 unresolved"."""
    if not options:
        return "No options with verified evidence were found."
    counts = Counter(option.status for option in options)
    parts = [f"{counts[status]} {status}" for status in STATUSES if counts[status]]
    noun = "option" if len(options) == 1 else "options"
    return f"{len(options)} {noun}: " + ", ".join(parts)


# Refined reasons


def reason_context(thread: Thread, option: Option, max_tokens: int) -> list[Post]:
    """The full posts behind the option's evidence plus its status post, in thread order, within ``max_tokens``.

    Posts are found by id. The status post always stays; when the others do
    not all fit, the posts closest to it are kept first.
    """
    wanted = {evidence.post_id for evidence in option.evidence}
    if option.status_post is not None:
        wanted.add(option.status_post)
    found = [post for post in thread.posts if post.id in wanted and post.spans]
    if not found:
        return []
    anchor = next((post.seq for post in found if post.id == option.status_post), max(post.seq for post in found))
    chosen: list[Post] = []
    used = 0
    for post in sorted(found, key=lambda post: (abs(post.seq - anchor), post.seq)):
        cost = estimate_tokens(render_post(post))
        if chosen and used + cost > max_tokens:
            continue
        chosen.append(post)
        used += cost
    return sorted(chosen, key=lambda post: post.seq)


def refine_reasons(llm: LLM, thread: Thread, options: list[Option], max_tokens: int = 12000) -> None:
    """Rewrite the reasons of decided options from their own posts; every new reason must cite that context.

    The context is cut to ``max_tokens`` but kept in thread order: NVIDIA's
    order-preserving RAG result found a capped context in original order beat
    both a long context and a relevance-sorted one. The prompt also lists every
    option with its summary, so reasons about the others can be left out. The
    model sees the context posts' aliases (``p12.s3``) only, so a cite outside
    the context resolves to nothing. An option keeps its MAP reasons when the
    output is invalid or no new reason cites its context. New reasons are
    "unchecked" until ``check_support`` runs.
    """
    order = {post.id: post.seq for post in thread.posts}
    known = [(option.key, option.title, option.summary) for option in options]
    for option in options:
        if option.status not in DECIDED_STATUSES:
            continue
        context = reason_context(thread, option, max_tokens)
        if not context:
            continue
        aliases = build_aliases([(post, 1, len(post.spans)) for post in context])
        messages = refine_messages(option.title, option.status, context, thread_title=thread.title, known=known)
        try:
            data = llm.complete_json("refine_reasons", messages, RefineOutput, think=False)
            proposals = RefineOutput.model_validate(data).reasons
        except (LLMOutputError, ValidationError) as exc:
            log.warning("refine_reasons skipped for %s: %s", option.key, exc)
            continue
        reasons: list[Reason] = []
        for proposal in proposals:
            text = " ".join(proposal.text.split())
            pairs = resolve_aliases(aliases, split_cites(proposal.cites))
            evidence = evidence_for(pairs, evidence_type="other")
            if text and evidence:
                add_reason(reasons, Reason(stance=proposal.stance, text=text, evidence=evidence), order)
        if reasons:
            option.reasons = reasons
            new_evidence = [item for reason in reasons for item in reason.evidence]
            option.evidence = merge_evidence(option.evidence + new_evidence, order)
        decide(option)
