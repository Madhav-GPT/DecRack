"""Keys, merging, events, the R2.4 status rules, reasons and confidence tiers."""

from __future__ import annotations

from decrack.models import Candidate, DecidedBy, Option, StatusEvent, Thread
from decrack.pipeline.consolidate import (
    AltRegistry,
    consolidate,
    decide,
    jaccard,
    normalize_text,
    rate_confidence,
    reconcile_with_outcome,
    same_title,
    similarity,
    summarize_outcome,
)
from decrack.pipeline.gate import GatedCandidate, make_evidence

STATEMENT = "decision_statement"


def item(
    thread: Thread,
    seq: int,
    act: str,
    title: str = "Soft keyword",
    evidence_type: str = "other",
    reason: str | None = "",
    sentences: tuple[int, ...] = (1,),
    alt_ref: str = "new",
) -> GatedCandidate:
    """A gated candidate citing sentences of the post at ``seq``; role and author are that post's."""
    post = thread.post_by_seq(seq)
    candidate = Candidate(alt_ref=alt_ref, alternative=title, act=act, reason=reason, cites=[])
    return GatedCandidate(
        candidate=candidate,
        evidence=[make_evidence(post, list(sentences), evidence_type=evidence_type)],
        post=post,
        role=post.role,
        author=post.author,
        evidence_type=evidence_type,
    )


def pid(seq: int) -> str:
    return f"dpo:1:{seq}"


def event(
    seq: int, act: str, role: str, author: str, evidence_type: str = "other", support: str = "supported"
) -> StatusEvent:
    """An event in the post at ``seq``; decide() reads only the events, in their order."""
    return StatusEvent(
        post_id=pid(seq),
        act=act,
        role=role,
        author=author,
        evidence_type=evidence_type,
        support=support,
        status_after="proposed",
    )


def decided(*events: StatusEvent) -> Option:
    option = Option(key="A1", title="Soft keyword", status_history=list(events))
    decide(option)
    return option


def only(options: list[Option]) -> Option:
    assert len(options) == 1
    return options[0]


def state(option: Option) -> tuple:
    return option.status, option.status_kind, option.status_basis, option.status_post


def after(option: Option) -> list[str]:
    return [item.status_after for item in option.status_history]


def cited(evidence) -> list[tuple[str, list[int]]]:
    return [(item.post_id, item.sentence_indexes) for item in evidence]


# Status rules (decide)


def test_a_supported_decision_statement_is_confirmed():
    by_decider = decided(
        event(7, "propose", "participant", "frank", "proposal"),
        event(8, "accept", "decider", "sam", STATEMENT),
    )
    assert state(by_decider) == ("accepted", "confirmed", "decider_statement", pid(8))
    assert by_decider.decided_by == DecidedBy(handle="sam", role="decider")
    assert (by_decider.status_note, by_decider.confidence) == ("", "high")

    by_author = decided(
        event(2, "propose", "participant", "bob", "proposal"),
        event(5, "reject", "author", "alice", STATEMENT),
    )
    assert state(by_author) == ("rejected", "confirmed", "author_statement", pid(5))
    assert by_author.decided_by == DecidedBy(handle="alice", role="author")
    assert (by_author.status_note, by_author.confidence) == ("", "high")


def test_a_later_decider_statement_supersedes_the_author():
    option = decided(
        event(5, "reject", "author", "alice", STATEMENT),
        event(8, "accept", "decider", "sam", STATEMENT),
    )
    assert state(option) == ("accepted", "confirmed", "decider_statement", pid(8))
    assert option.decided_by == DecidedBy(handle="sam", role="decider")
    assert after(option) == ["rejected", "accepted"]


def test_a_later_author_statement_against_the_decider_is_contested():
    option = decided(
        event(3, "reject", "decider", "sam", STATEMENT),
        event(5, "accept", "author", "alice", STATEMENT),
    )
    assert state(option) == ("rejected", "contested", "decider_statement", pid(3))
    assert option.decided_by == DecidedBy(handle="sam", role="decider")
    assert option.confidence == "low"
    assert after(option) == ["rejected", "rejected"]

    # The decider saying it again afterwards resolves the conflict.
    resolved = decided(
        event(3, "reject", "decider", "sam", STATEMENT),
        event(5, "accept", "author", "alice", STATEMENT),
        event(8, "reject", "decider", "sam", STATEMENT),
    )
    assert state(resolved) == ("rejected", "confirmed", "decider_statement", pid(8))


def test_a_later_contrary_act_of_any_type_by_author_or_decider_contests():
    argued = decided(
        event(5, "reject", "author", "alice", STATEMENT),
        event(8, "support", "decider", "sam", "support"),
    )
    assert state(argued) == ("rejected", "contested", "author_statement", pid(5))
    assert argued.confidence == "low"

    # An act that points the same way does not.
    agreed = decided(
        event(5, "reject", "author", "alice", STATEMENT),
        event(8, "object", "decider", "sam", "objection"),
    )
    assert state(agreed) == ("rejected", "confirmed", "author_statement", pid(5))
    assert agreed.confidence == "high"


def test_the_later_of_two_author_statements_wins():
    option = decided(
        event(1, "accept", "author", "alice", STATEMENT),
        event(5, "reject", "author", "alice", STATEMENT),
    )
    assert state(option) == ("rejected", "confirmed", "author_statement", pid(5))
    assert option.decided_by == DecidedBy(handle="alice", role="author")
    assert after(option) == ["accepted", "rejected"]


def test_participants_never_contest_a_decision():
    option = decided(
        event(3, "reject", "decider", "sam", STATEMENT),
        event(5, "support", "participant", "bob", "support"),
        event(6, "accept", "participant", "erin", STATEMENT),
        event(7, "propose", "maintainer", "dave", "proposal"),
    )
    assert state(option) == ("rejected", "confirmed", "decider_statement", pid(3))
    assert option.confidence == "high"
    assert after(option) == ["rejected"] * 4


def test_an_author_objection_is_an_inferred_rejection():
    option = decided(
        event(2, "propose", "participant", "bob", "proposal"),
        event(5, "object", "author", "alice", "objection"),
    )
    assert state(option) == ("rejected", "inferred", "author_statement", pid(5))
    assert option.decided_by == DecidedBy(handle="alice", role="author")
    assert (option.status_note, option.confidence) == ("", "medium")

    # The author's latest act counts, whatever its evidence type.
    deferred = decided(
        event(1, "object", "author", "alice", "objection"),
        event(5, "defer", "author", "alice", "author_position"),
    )
    assert state(deferred) == ("deferred", "inferred", "author_statement", pid(5))

    # Later backing by the author or a decider undoes it.
    backed = decided(
        event(5, "object", "author", "alice", "objection"),
        event(8, "support", "decider", "sam", "support"),
    )
    assert state(backed) == ("unresolved", "unresolved", "none", None)
    assert backed.decided_by is None


def test_objections_from_two_participants_are_a_weaker_inferred_rejection():
    option = decided(
        event(2, "propose", "participant", "bob", "proposal"),
        event(3, "object", "participant", "carol", "objection"),
        event(4, "reject", "maintainer", "dave", "objection"),
    )
    assert state(option) == ("rejected", "inferred", "participant_consensus", pid(4))
    assert option.status_note == "inferred from objections by 2 participants (weaker)"
    assert option.decided_by is None
    assert option.confidence == "medium"

    one_person = decided(
        event(2, "propose", "participant", "bob", "proposal"),
        event(3, "object", "participant", "carol", "objection"),
        event(6, "object", "participant", "carol", "objection"),
    )
    assert state(one_person) == ("unresolved", "unresolved", "none", None)
    assert (one_person.status_note, one_person.confidence) == ("", "low")

    backed_by_the_author = decided(
        event(3, "object", "participant", "carol", "objection"),
        event(5, "support", "author", "alice", "support"),
        event(6, "object", "participant", "erin", "objection"),
    )
    assert state(backed_by_the_author) == ("unresolved", "unresolved", "none", None)


def test_rule_one_reads_unsupported_statements_and_the_other_rules_ignore_them():
    option = decided(
        event(7, "propose", "participant", "frank", "proposal"),
        event(8, "accept", "decider", "sam", STATEMENT, support="unsupported"),
    )
    assert state(option) == ("accepted", "inferred", "decider_statement", pid(8))
    assert option.confidence == "low"
    assert after(option) == ["proposed", "accepted"]

    # Rule 1 walks every event, so an unsupported later statement still contests.
    contested = decided(
        event(3, "reject", "decider", "sam", STATEMENT),
        event(5, "accept", "author", "alice", STATEMENT, support="unsupported"),
    )
    assert state(contested) == ("rejected", "contested", "decider_statement", pid(3))

    # Rules 2-4 still ignore unsupported events.
    ignored = decided(event(5, "object", "author", "alice", "objection", support="unsupported"))
    assert state(ignored) == ("unresolved", "unresolved", "none", None)


def test_a_decision_statement_is_confirmed_unless_the_support_check_says_unsupported():
    # Support check off: every event stays "unchecked", and an author or decider statement is confirmed.
    by_author = decided(event(5, "reject", "author", "alice", STATEMENT, support="unchecked"))
    assert state(by_author) == ("rejected", "confirmed", "author_statement", pid(5))
    assert by_author.confidence == "high"
    by_decider = decided(event(8, "accept", "decider", "sam", STATEMENT, support="unchecked"))
    assert state(by_decider) == ("accepted", "confirmed", "decider_statement", pid(8))
    assert by_decider.confidence == "high"

    # Support check on.
    unsupported = decided(event(8, "accept", "decider", "sam", STATEMENT, support="unsupported"))
    assert (unsupported.status_kind, unsupported.confidence) == ("inferred", "low")
    supported = decided(event(8, "accept", "decider", "sam", STATEMENT, support="supported"))
    assert (supported.status_kind, supported.confidence) == ("confirmed", "high")
    partial = decided(event(5, "reject", "author", "alice", STATEMENT, support="partial"))
    assert (partial.status_kind, partial.confidence) == ("confirmed", "medium")


def test_confidence_tiers():
    cases = [
        ([event(8, "accept", "decider", "sam", STATEMENT)], "confirmed", "high"),
        ([event(8, "accept", "decider", "sam", STATEMENT, support="unchecked")], "confirmed", "high"),
        ([event(8, "accept", "decider", "sam", STATEMENT, support="partial")], "confirmed", "medium"),
        ([event(8, "accept", "decider", "sam", STATEMENT, support="unsupported")], "inferred", "low"),
        ([event(5, "object", "author", "alice", "objection")], "inferred", "medium"),
        ([event(5, "object", "author", "alice", "objection", support="partial")], "inferred", "low"),
        (
            [
                event(3, "object", "participant", "carol", "objection"),
                event(6, "object", "participant", "erin", "objection"),
            ],
            "inferred",
            "medium",
        ),
        (
            [
                event(3, "object", "participant", "carol", "objection"),
                event(6, "object", "participant", "erin", "objection", support="unchecked"),
            ],
            "inferred",
            "low",
        ),
        (
            [event(3, "reject", "decider", "sam", STATEMENT), event(5, "support", "author", "alice", "support")],
            "contested",
            "low",
        ),
        ([event(7, "propose", "participant", "frank", "proposal")], "unresolved", "low"),
    ]
    for events, kind, confidence in cases:
        option = decided(*events)
        assert (option.status_kind, option.confidence) == (kind, confidence)
        assert rate_confidence(option) == confidence


def test_status_after_follows_each_event():
    option = decided(
        event(2, "propose", "participant", "bob", "proposal"),
        event(3, "object", "participant", "carol", "objection"),
        event(4, "object", "maintainer", "dave", "objection"),
        event(5, "support", "author", "alice", "support"),
        event(8, "accept", "decider", "sam", STATEMENT),
    )
    assert after(option) == ["proposed", "unresolved", "rejected", "unresolved", "accepted"]
    assert state(option) == ("accepted", "confirmed", "decider_statement", pid(8))


# Events, reasons and evidence (consolidate)


def test_consolidate_builds_events_in_thread_order(synthetic_thread):
    t = synthetic_thread
    soft_reason = "It keeps lazy usable as a normal name."
    gated = [
        item(t, 8, "accept", evidence_type=STATEMENT),
        item(t, 7, "propose", evidence_type="proposal", reason=soft_reason, sentences=(2,)),
        # The same act in the same post again (overlapping windows) only adds its evidence.
        item(t, 7, "propose", evidence_type="proposal"),
        item(t, 7, "support", evidence_type="support", sentences=(2,)),
    ]
    option = only(consolidate(t, gated))
    frank, sam = t.post_by_seq(7).id, t.post_by_seq(8).id
    assert [(e.post_id, e.act, e.role, e.author, e.evidence_type, e.support) for e in option.status_history] == [
        (frank, "propose", "participant", "frank", "proposal", "unchecked"),
        (frank, "support", "participant", "frank", "support", "unchecked"),
        (sam, "accept", "decider", "sam", STATEMENT, "unchecked"),
    ]
    assert cited(option.status_history[0].evidence) == [(frank, [1]), (frank, [2])]
    assert cited(option.evidence) == [(frank, [1]), (frank, [2]), (sam, [1])]
    assert option.summary == "It keeps lazy usable as a normal name."
    # Items without a reason (other than proposals) fall back to their first quote.
    assert [(reason.stance, reason.text, reason.support) for reason in option.reasons] == [
        ("pro", "It keeps lazy usable as a normal name.", "unchecked"),
        ("pro", "A soft keyword keeps lazy usable as a normal name.", "unchecked"),
        ("pro", "The Steering Council accepts PEP 9999 with the soft keyword.", "unchecked"),
    ]

    # Nothing is support-checked (the check is off): the decider's statement is confirmed.
    assert state(option) == ("accepted", "confirmed", "decider_statement", sam)
    assert option.decided_by == DecidedBy(handle="sam", role="decider")
    assert option.confidence == "high"

    for item_event in option.status_history:
        item_event.support = "supported"
    decide(option)
    assert (option.status_kind, option.confidence) == ("confirmed", "high")


def test_reasons_get_stances_and_near_duplicates_merge(synthetic_thread):
    t = synthetic_thread
    gated = [
        item(t, 3, "object", title="Hard keyword", reason="It breaks existing code.", sentences=(2,)),
        item(t, 8, "reject", title="Hard keyword", reason="it breaks existing code", sentences=(2,)),
        item(t, 1, "propose", title="Hard keyword", reason="Widgets are created on first access.", sentences=(2,)),
        item(t, 1, "support", title="Hard keyword", sentences=(2,)),
    ]
    option = only(consolidate(t, gated))
    first, third, eighth = (t.post_by_seq(seq).id for seq in (1, 3, 8))
    assert [(reason.stance, reason.text) for reason in option.reasons] == [
        ("pro", "Widgets are created on first access."),
        ("pro", "Widgets would be created on first access with a new lazy keyword."),  # the support's quote
        ("con", "It breaks existing code."),
    ]
    assert cited(option.reasons[2].evidence) == [(third, [2]), (eighth, [2])]
    assert cited(option.evidence) == [(first, [2]), (third, [2]), (eighth, [2])]


def test_a_missing_reason_falls_back_to_the_first_quote_clipped(synthetic_thread):
    t = synthetic_thread
    option = only(consolidate(t, [item(t, 5, "reject", reason=None, sentences=(2, 3)), item(t, 4, "propose")]))
    quote = " ".join(t.post_by_seq(5).sentences[1:3])
    assert len(quote) > 150
    assert [(reason.stance, reason.text) for reason in option.reasons] == [("con", quote[:300])]


def test_defer_reasons_are_con(synthetic_thread):
    t = synthetic_thread
    option = only(consolidate(t, [item(t, 8, "defer", reason="Not now."), item(t, 7, "support", reason="Useful.")]))
    assert [(reason.stance, reason.text) for reason in option.reasons] == [("pro", "Useful."), ("con", "Not now.")]


# Keys and merging


def test_registry_keeps_known_keys_reuses_similar_titles_and_keeps_summaries(synthetic_thread):
    t = synthetic_thread
    registry = AltRegistry()
    assert registry.assign(item(t, 7, "propose", title="Use a soft keyword")) == "A1"
    soft_reason = "It keeps lazy usable as a normal name."
    assert registry.assign(item(t, 8, "accept", title="use a SOFT keyword.", reason=soft_reason)) == "A1"
    messy_reason = "Widgets  are created\non first access."
    assert registry.assign(item(t, 1, "propose", title="Hard keyword", reason=messy_reason)) == "A2"
    # A valid known key wins over the name; the first reason filed under a key stays its summary.
    later_reason = "It breaks existing code."
    assert registry.assign(item(t, 3, "object", title="Something else", alt_ref="a2", reason=later_reason)) == "A2"
    assert registry.assign(item(t, 2, "propose", title="Decorator", alt_ref="A9")) == "A3"
    assert registry.assign(item(t, 4, "propose", title=" ", reason="No name, so no key.")) is None
    long_name = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    long_reason = " ".join(f"w{n}" for n in range(1, 26))
    assert registry.assign(item(t, 4, "propose", title=long_name, reason=long_reason)) == "A4"
    assert registry.known() == [
        ("A1", "Use a soft keyword", "It keeps lazy usable as a normal name."),
        ("A2", "Hard keyword", "Widgets are created on first access."),
        ("A3", "Decorator", ""),
        (
            "A4",
            "one two three four five six seven eight nine ten eleven twelve",
            " ".join(f"w{n}" for n in range(1, 21)),
        ),
    ]


def test_titles_sharing_most_words_merge_without_a_model(synthetic_thread):
    t = synthetic_thread
    first, second = normalize_text("Lazy imports by default"), normalize_text("lazy imports default")
    assert jaccard(first, second) == 0.75 and same_title(first, second)
    # Reordered words: difflib alone misses them, the token-set Jaccard (3 of 4 words) does not.
    reordered = normalize_text("Default lazy imports")
    assert similarity(first, reordered) < 0.85 and jaccard(first, reordered) == 0.75
    assert not same_title(normalize_text("Soft keyword"), normalize_text("Hard keyword"))

    registry = AltRegistry()
    assert registry.assign(item(t, 2, "propose", title="Lazy imports by default")) == "A1"
    assert registry.assign(item(t, 4, "propose", title="lazy imports default")) == "A1"
    assert registry.assign(item(t, 5, "reject", title="Default lazy imports")) == "A1"
    assert registry.assign(item(t, 7, "propose", title="Soft keyword")) == "A2"

    gated = [
        item(t, 2, "propose", title="Lazy imports by default"),
        item(t, 7, "propose", title="Soft keyword"),
        item(t, 5, "reject", title="Default lazy imports"),
    ]
    options = consolidate(t, gated)
    assert [(o.key, o.title) for o in options] == [("A1", "Lazy imports by default"), ("A2", "Soft keyword")]
    assert [(t.post_by_id(e.post_id).seq, e.act) for e in options[0].status_history] == [(2, "propose"), (5, "reject")]


def test_summarize_outcome():
    def options(*statuses: str) -> list[Option]:
        return [Option(key=f"A{n}", title=f"Option {n}", status=status) for n, status in enumerate(statuses, start=1)]

    assert summarize_outcome([]) == "No options with verified evidence were found."
    assert summarize_outcome(options("accepted")) == "1 option: 1 accepted"
    mixed = ["unresolved", "rejected", "accepted"] + ["rejected"] * 7 + ["unresolved", "unresolved"]
    assert summarize_outcome(options(*mixed)) == "12 options: 1 accepted, 8 rejected, 3 unresolved"
    assert summarize_outcome(options("proposed", "withdrawn", "deferred")) == (
        "3 options: 1 withdrawn, 1 deferred, 1 proposed"
    )



def test_a_not_planned_thread_cannot_confirm_an_author_only_acceptance():
    def accepted(key: str, basis: str) -> Option:
        return Option(
            key=key, title=key, status="accepted", status_kind="confirmed", status_basis=basis, confidence="high"
        )

    by_author, by_decider = accepted("A1", "author_statement"), accepted("A2", "decider_statement")
    thread = Thread(id="gh:o/r#2077", kind="github_issue", meta={"state": "closed", "state_reason": "not_planned"})
    reconcile_with_outcome(thread, [by_author, by_decider])
    assert (by_author.status_kind, by_author.confidence) == ("contested", "low")
    assert "not planned" in by_author.status_note
    assert (by_decider.status_kind, by_decider.confidence) == ("confirmed", "high")

    unmerged_pr = Thread(id="gh:o/r#9", kind="github_pr", meta={"state": "closed", "merged": False})
    pr_option = accepted("A1", "author_statement")
    reconcile_with_outcome(unmerged_pr, [pr_option])
    assert pr_option.status_kind == "contested"

    completed = Thread(id="gh:o/r#10", kind="github_issue", meta={"state": "closed", "state_reason": "completed"})
    kept = accepted("A1", "author_statement")
    reconcile_with_outcome(completed, [kept])
    assert kept.status_kind == "confirmed"


def test_the_threads_own_proposal_is_rejected_by_github_metadata():
    def option(key: str, title: str, status: str, basis: str) -> Option:
        kind = "confirmed" if basis != "none" else "unresolved"
        return Option(key=key, title=title, status=status, status_kind=kind, status_basis=basis, confidence="high")

    issue = Thread(
        id="gh:astral-sh/uv#2077",
        kind="github_issue",
        title="Support `--user` flag for `uv pip install`",
        meta={"state": "closed", "state_reason": "not_planned", "closed_by": "maint"},
    )
    own = option("A1", "Support --user flag", "accepted", "author_statement")
    other = option("A2", "Use a virtual environment instead", "accepted", "author_statement")
    decided = option("A3", "Support --user flag on Windows", "accepted", "decider_statement")
    reconcile_with_outcome(issue, [own, other, decided])
    assert (own.status, own.status_kind, own.confidence) == ("rejected", "inferred", "low")
    assert own.status_note == "closed as not planned by @maint (GitHub metadata)"
    assert (other.status, other.status_kind) == ("accepted", "contested")
    assert (decided.status, decided.status_kind) == ("accepted", "confirmed")  # a decider statement stays

    closed = {"state": "closed", "merged": False}
    pr = Thread(id="gh:o/r#9", kind="github_pr", title="Add a caching layer for metadata", meta=closed)
    approach = option("A1", "Caching layer", "proposed", "none")
    reconcile_with_outcome(pr, [approach])
    assert (approach.status, approach.status_kind) == ("rejected", "inferred")
    assert approach.status_note == "closed without merging (GitHub metadata)"
