"""check_support: batched semantic-support verdicts on status events, reasons and their evidence."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from decrack.models import Candidate, Option, Reason, StatusEvent, Thread
from decrack.pipeline.consolidate import consolidate, decide
from decrack.pipeline.gate import GatedCandidate, make_evidence
from decrack.pipeline.llm import ScriptedLLM
from decrack.pipeline.support import SUPPORT_SYSTEM, SupportOutput, check_support


def event(thread: Thread, seq: int, act: str, sentences: tuple[int, ...] = (1,)) -> StatusEvent:
    """An event by the writer of the post at ``seq``, citing some of its sentences."""
    post = thread.post_by_seq(seq)
    return StatusEvent(
        post_id=post.id,
        act=act,
        role=post.role,
        author=post.author,
        evidence=[make_evidence(post, list(sentences))],
        status_after="proposed",
    )


def reason(thread: Thread, stance: str, text: str, seq: int, sentences: tuple[int, ...] = (1,)) -> Reason:
    post = thread.post_by_seq(seq)
    return Reason(stance=stance, text=text, evidence=[make_evidence(post, list(sentences))])


def gated_item(
    thread: Thread, seq: int, act: str, evidence_type: str, reason_text: str = "", sentences: tuple[int, ...] = (1,)
) -> GatedCandidate:
    """A gated candidate about "Use a decorator" citing sentences of the post at ``seq``."""
    post = thread.post_by_seq(seq)
    candidate = Candidate(
        alt_ref="new",
        alternative="Use a decorator",
        act=act,
        reason=reason_text,
        cites=[],
    )
    return GatedCandidate(
        candidate=candidate,
        evidence=[make_evidence(post, list(sentences), evidence_type=evidence_type)],
        post=post,
        role=post.role,
        author=post.author,
        evidence_type=evidence_type,
    )


def verdicts(*values: str) -> dict:
    """A support answer giving ``values`` to claims 1, 2, ... in order."""
    return {"results": [{"id": number, "verdict": value} for number, value in enumerate(values, start=1)]}


def claim_lines(messages: list[dict]) -> list[str]:
    return [line for line in messages[-1]["content"].splitlines() if line.startswith("Claim ")]


def supports(items) -> list[str]:
    return [item.support for item in items]


def soft_option(thread: Thread) -> Option:
    """Three claims: two events and one reason."""
    return Option(
        key="A1",
        title="Soft keyword",
        status_history=[event(thread, 7, "propose"), event(thread, 8, "accept")],
        reasons=[reason(thread, "pro", "It keeps lazy usable as a normal name.", 7, (2,))],
    )


def test_claims_go_in_batches(synthetic_thread):
    t = synthetic_thread
    hard = Option(
        key="A1",
        title="Hard keyword",
        status_history=[
            event(t, 1, "propose", (2,)),
            event(t, 3, "object"),
            # No evidence, so nothing to check.
            StatusEvent(
                post_id=t.post_by_seq(5).id, act="object", role="author", author="alice", status_after="proposed"
            ),
            event(t, 6, "object"),
            event(t, 8, "reject", (2,)),
        ],
        reasons=[
            reason(t, "con", "It breaks existing code.", 3, (2,)),
            reason(t, "pro", "Widgets are created on first access.", 1, (2,)),
        ],
    )
    soft = soft_option(t)  # 4 + 2 claims above, 3 here: 9 in all
    llm = ScriptedLLM({"support": [verdicts(*["supported"] * 8), verdicts("partial")]})

    assert check_support(llm, [hard, soft], batch_size=8) == 2
    assert llm.calls == 2
    assert [len(claim_lines(request[1])) for request in llm.requests] == [8, 1]
    assert claim_lines(llm.requests[1][1]) == [
        'Claim 1: A reason for the option "Soft keyword": It keeps lazy usable as a normal name.'
    ]
    assert supports(hard.status_history) == ["supported", "supported", "unchecked", "supported", "supported"]
    assert supports(hard.reasons) == ["supported", "supported"]
    assert supports(soft.status_history) == ["supported", "supported"]
    assert supports(soft.reasons) == ["partial"]
    assert supports(soft.reasons[0].evidence) == ["partial"]


def test_verdicts_land_on_events_reasons_and_their_evidence(synthetic_thread):
    t = synthetic_thread
    [option] = consolidate(
        t,
        [
            gated_item(t, 2, "propose", "proposal"),
            gated_item(t, 5, "reject", "decision_statement", "Decorators cannot apply to import statements.", (2,)),
        ],
    )
    # Not checked yet (as with the support check off): the author's decision statement is confirmed.
    assert (option.status, option.status_kind, option.confidence) == ("rejected", "confirmed", "high")

    llm = ScriptedLLM({"support": [verdicts("partial", "supported", "unsupported")]})
    assert check_support(llm, [option]) == 1

    system, user = llm.requests[0][1]
    assert system == {"role": "system", "content": SUPPORT_SYSTEM}
    assert "untrusted" in SUPPORT_SYSTEM
    # Only the claims and their quotes: no thread title, no authors, no other posts.
    assert user["content"] == (
        'Claim 1: The quoted text proposes the option "Use a decorator".\n'
        'Quote 1.1: "Why not use a decorator instead of a new keyword?"\n'
        "\n"
        'Claim 2: The quoted text rejects the option "Use a decorator".\n'
        'Quote 2.1: "We rejected the decorator approach because decorators cannot apply to import statements."\n'
        "\n"
        'Claim 3: A reason against the option "Use a decorator": Decorators cannot apply to import statements.\n'
        'Quote 3.1: "We rejected the decorator approach because decorators cannot apply to import statements."'
    )

    propose, reject = option.status_history
    assert (propose.support, supports(propose.evidence)) == ("partial", ["partial"])
    assert (reject.support, supports(reject.evidence)) == ("supported", ["supported"])
    [because] = option.reasons
    assert (because.support, supports(because.evidence)) == ("unsupported", ["unsupported"])
    # The event and the reason quote the same sentence, yet each keeps its own verdict.
    assert reject.evidence[0].quote == because.evidence[0].quote
    assert supports(option.evidence) == ["partial", "supported"]

    decide(option)
    assert (option.status, option.status_kind, option.status_basis, option.confidence) == (
        "rejected",
        "confirmed",
        "author_statement",
        "high",
    )


def test_an_unsupported_verdict_leaves_the_statement_only_inferred(synthetic_thread):
    t = synthetic_thread
    [option] = consolidate(t, [gated_item(t, 5, "reject", "decision_statement", sentences=(2,))])
    assert (option.status_kind, option.confidence) == ("confirmed", "high")

    check_support(ScriptedLLM({"support": [verdicts("unsupported")]}), [option])
    decide(option)
    assert (option.status, option.status_kind, option.status_basis) == ("rejected", "inferred", "author_statement")
    assert option.confidence == "low"

    check_support(ScriptedLLM({"support": [verdicts("supported")]}), [option])
    decide(option)
    assert (option.status, option.status_kind, option.confidence) == ("rejected", "confirmed", "high")


def test_bad_output_or_a_missing_id_leaves_claims_unchecked(synthetic_thread):
    t = synthetic_thread
    option = soft_option(t)
    invalid = ScriptedLLM({"support": [{"results": "oops"}, {"results": [{"id": 1, "verdict": "maybe"}]}]})
    assert check_support(invalid, [option]) == 1
    assert check_support(invalid, [option]) == 1
    claims = option.status_history + option.reasons
    assert supports(claims) == ["unchecked"] * 3
    assert supports([evidence for claim in claims for evidence in claim.evidence]) == ["unchecked"] * 3

    option = soft_option(t)
    answer = ScriptedLLM({"support": [{"results": [{"id": 2, "verdict": "supported"}]}]})
    assert check_support(answer, [option]) == 1
    assert supports(option.status_history) == ["unchecked", "supported"]
    assert supports(option.reasons) == ["unchecked"]
    assert supports(option.reasons[0].evidence) == ["unchecked"]


def test_ids_outside_the_batch_are_ignored(synthetic_thread):
    t = synthetic_thread
    option = Option(key="A1", title="Soft keyword", status_history=[event(t, 7, "propose"), event(t, 8, "accept")])
    first = [
        {"id": 0, "verdict": "unsupported"},
        {"id": 2, "verdict": "unsupported"},  # beyond this batch of one claim
        {"id": 1, "verdict": "supported"},
        {"id": 1, "verdict": "unsupported"},  # the first result for a number wins
    ]
    second = [{"id": 1, "verdict": "partial"}, {"id": 2, "verdict": "supported"}]
    llm = ScriptedLLM({"support": [{"results": first}, {"results": second}]})

    assert check_support(llm, [option], batch_size=1) == 2
    assert [len(claim_lines(request[1])) for request in llm.requests] == [1, 1]
    assert supports(option.status_history) == ["supported", "partial"]


def test_no_claims_means_no_calls():
    llm = ScriptedLLM()
    uncited = Option(
        key="A1",
        title="Nothing cited",
        status_history=[StatusEvent(post_id="x:1", act="propose", role="author", status_after="proposed")],
        reasons=[Reason(stance="pro", text="No quote.")],
    )
    assert check_support(llm, [uncited]) == 0
    assert check_support(llm, []) == 0
    assert llm.calls == 0


def test_support_output_allows_three_verdicts():
    parsed = SupportOutput.model_validate({"results": [{"id": 2, "verdict": "partial"}]})
    assert [(result.id, result.verdict) for result in parsed.results] == [(2, "partial")]
    with pytest.raises(ValidationError):
        SupportOutput.model_validate({"results": [{"id": 1, "verdict": "maybe"}]})
