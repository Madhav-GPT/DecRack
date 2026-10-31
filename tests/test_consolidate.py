"""Keys, merging, events, the R2.4 status rules, reasons and confidence tiers."""

from __future__ import annotations

from decrack.models import Candidate, DecidedBy, Option, StatusEvent, Thread
from decrack.pipeline.consolidate import (
    AltRegistry,
    consolidate,
    decide,
    rate_confidence,
    refine_reasons,
    summarize_outcome,
)
from decrack.pipeline.gate import GatedCandidate, make_evidence
from decrack.pipeline.llm import ScriptedLLM

STATEMENT = "decision_statement"


def item(
    thread: Thread,
    seq: int,
    act: str,
    title: str = "Soft keyword",
    evidence_type: str = "other",
    reason: str = "",
    sentences: tuple[int, ...] = (1,),
    alt_ref: str = "new",
) -> GatedCandidate:
    """A gated candidate citing sentences of the post at ``seq``; role and author are that post's."""
    post = thread.post_by_seq(seq)
    candidate = Candidate(
        alt_ref=alt_ref, alternative=title, act=act, evidence_type=evidence_type, reason=reason, cites=[]
    )
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


def test_unsupported_events_are_ignored():
    option = decided(
        event(7, "propose", "participant", "frank", "proposal"),
        event(8, "accept", "decider", "sam", STATEMENT, support="unsupported"),
    )
    assert state(option) == ("proposed", "unresolved", "none", None)
    assert after(option) == ["proposed", "proposed"]

    not_contested = decided(
        event(3, "reject", "decider", "sam", STATEMENT),
        event(5, "accept", "author", "alice", STATEMENT, support="unsupported"),
    )
    assert state(not_contested) == ("rejected", "confirmed", "decider_statement", pid(3))


def test_an_unchecked_or_partial_statement_is_only_inferred():
    unchecked = decided(event(8, "accept", "decider", "sam", STATEMENT, support="unchecked"))
    assert state(unchecked) == ("accepted", "inferred", "decider_statement", pid(8))
    assert unchecked.confidence == "low"

    partial = decided(event(5, "reject", "author", "alice", STATEMENT, support="partial"))
    assert state(partial) == ("rejected", "inferred", "author_statement", pid(5))
    assert partial.confidence == "low"


def test_confidence_tiers():
    cases = [
        ([event(8, "accept", "decider", "sam", STATEMENT)], "confirmed", "high"),
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
    assert [(reason.stance, reason.text, reason.support) for reason in option.reasons] == [
        ("pro", "It keeps lazy usable as a normal name.", "unchecked")
    ]

    # Nothing is support-checked yet, so the decider's statement is only inferred.
    assert state(option) == ("accepted", "inferred", "decider_statement", sam)
    assert option.decided_by == DecidedBy(handle="sam", role="decider")
    assert option.confidence == "low"

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
        ("con", "It breaks existing code."),
    ]
    assert cited(option.reasons[1].evidence) == [(third, [2]), (eighth, [2])]
    assert cited(option.evidence) == [(first, [2]), (third, [2]), (eighth, [2])]


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


def test_llm_merge_joins_alternatives_into_the_lowest_key(synthetic_thread):
    t = synthetic_thread
    gated = [
        item(t, 2, "propose", title="Use a decorator", evidence_type="proposal"),
        item(t, 4, "propose", title="Global flag", evidence_type="proposal"),
        item(
            t,
            5,
            "reject",
            title="Decorator approach",
            evidence_type=STATEMENT,
            reason="Decorators cannot apply to import statements.",
            sentences=(2,),
        ),
    ]
    # Valid group: A3 with A1. Ignored: an unknown key (A7) and a key that is already in a group (A1).
    llm = ScriptedLLM({"merge": [{"groups": [["a3", "A1"], ["A2", "A7"], ["A1", "A2"]]}]})
    options = consolidate(t, gated, llm)

    assert llm.calls == 1
    step, messages = llm.requests[0][0], llm.requests[0][1]
    assert step == "merge"
    content = messages[-1]["content"]
    for key, title in (("A1", "Use a decorator"), ("A2", "Global flag"), ("A3", "Decorator approach")):
        assert key in content and title in content
    assert "Decorators cannot apply to import statements." in content  # A3's summary

    second, fourth, fifth = (t.post_by_seq(seq).id for seq in (2, 4, 5))
    assert [(o.key, o.title, o.status, o.status_kind, o.status_basis, o.status_post) for o in options] == [
        ("A1", "Use a decorator", "rejected", "inferred", "author_statement", fifth),
        ("A2", "Global flag", "proposed", "unresolved", "none", None),
    ]
    assert [(e.post_id, e.act) for e in options[0].status_history] == [(second, "propose"), (fifth, "reject")]
    assert [(e.post_id, e.act) for e in options[1].status_history] == [(fourth, "propose")]
    # A1 had no reason of its own; the summary comes from the merged A3.
    assert [o.summary for o in options] == ["Decorators cannot apply to import statements.", ""]


def test_merge_is_skipped_for_one_option_and_survives_bad_output(synthetic_thread):
    t = synthetic_thread
    silent = ScriptedLLM()  # it has no responses, so any call would fail
    assert len(consolidate(t, [item(t, 7, "propose")], silent)) == 1
    assert silent.calls == 0

    gated = [item(t, 2, "propose", title="Use a decorator"), item(t, 4, "propose", title="Global flag")]
    bad = ScriptedLLM({"merge": [{"groups": "not a list"}]})
    assert [option.title for option in consolidate(t, gated, bad)] == ["Use a decorator", "Global flag"]
    assert bad.calls == 1


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


# Refined reasons


def decided_option(thread: Thread) -> list[Option]:
    """One option, rejected by the author's statement in post 5, with evidence in posts 2 and 5."""
    gated = [
        item(
            thread,
            2,
            "propose",
            title="Decorator",
            evidence_type="proposal",
            reason="A decorator would avoid adding new syntax.",
            sentences=(1, 2),
        ),
        item(
            thread,
            5,
            "reject",
            title="Decorator",
            evidence_type=STATEMENT,
            reason="Decorators cannot apply.",
            sentences=(2,),
        ),
    ]
    return consolidate(thread, gated)


def test_refine_reasons_keeps_only_reasons_cited_from_the_context(synthetic_thread):
    t = synthetic_thread
    options = decided_option(t)
    reply = {
        "reasons": [
            {"stance": "con", "text": "Decorators cannot apply to import statements.", "cites": ["p5.s2"]},
            {"stance": "pro", "text": "It avoids new syntax.", "cites": ["p2.s2"]},
            {"stance": "con", "text": "This cites a post outside the context.", "cites": ["p8.s2"]},
            {"stance": "con", "text": "No cites at all.", "cites": []},
        ]
    }
    llm = ScriptedLLM({"refine_reasons": [reply]})
    refine_reasons(llm, t, options)

    option = options[0]
    second, fifth = t.post_by_seq(2).id, t.post_by_seq(5).id
    assert [(r.stance, r.text, r.support, cited(r.evidence)) for r in option.reasons] == [
        ("con", "Decorators cannot apply to import statements.", "unchecked", [(fifth, [2])]),
        ("pro", "It avoids new syntax.", "unchecked", [(second, [2])]),
    ]
    assert all((e.support, e.evidence_type) == ("unchecked", "other") for r in option.reasons for e in r.evidence)
    assert cited(option.evidence) == [(second, [1, 2]), (second, [2]), (fifth, [2])]
    assert state(option) == ("rejected", "inferred", "author_statement", fifth)

    # The context is the option's own posts (2 and 5), in thread order.
    assert llm.calls == 1
    step, messages = llm.requests[0][0], llm.requests[0][1]
    assert step == "refine_reasons"
    content = messages[-1]["content"]
    assert "Decorator" in content and "rejected" in content
    assert "[p2.s2]" in content and "[p5.s2]" in content
    assert content.index("[p2.s1]") < content.index("[p5.s1]")
    assert "[p8." not in content


def test_refine_reasons_keeps_map_reasons_when_nothing_usable_comes_back(synthetic_thread):
    t = synthetic_thread
    options = decided_option(t)
    before = [reason.model_copy(deep=True) for reason in options[0].reasons]
    assert [(reason.stance, reason.text) for reason in before] == [
        ("pro", "A decorator would avoid adding new syntax."),
        ("con", "Decorators cannot apply."),
    ]

    refine_reasons(ScriptedLLM({"refine_reasons": [{"reasons": "oops"}]}), t, options)
    assert options[0].reasons == before

    outside_context = {"reasons": [{"stance": "pro", "text": "Unrelated.", "cites": ["p1.s1", "p8.s1"]}]}
    refine_reasons(ScriptedLLM({"refine_reasons": [outside_context]}), t, options)
    assert options[0].reasons == before


def test_refine_context_keeps_the_status_post_within_the_budget(synthetic_thread):
    t = synthetic_thread
    options = decided_option(t)
    llm = ScriptedLLM({"refine_reasons": [{"reasons": []}]})
    refine_reasons(llm, t, options, max_tokens=1)
    content = llm.requests[0][1][-1]["content"]
    assert "[p5.s1]" in content
    assert "[p2.s1]" not in content


def test_refine_reasons_skips_undecided_options(synthetic_thread):
    t = synthetic_thread
    options = consolidate(t, [item(t, 7, "propose")])
    assert options[0].status == "proposed"
    llm = ScriptedLLM()
    refine_reasons(llm, t, options)
    assert llm.calls == 0
