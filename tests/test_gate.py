"""The gate resolves aliases only through the prompt's alias table and cuts every quote from the post text."""

from __future__ import annotations

import pytest

from decrack.models import Candidate, Evidence, Post, Thread, sentence_alias
from decrack.pipeline.gate import (
    DECISION_CUES,
    build_aliases,
    derive_evidence_type,
    evidence_for,
    gate_candidates,
    make_evidence,
    resolve_aliases,
    split_cites,
)
from decrack.pipeline.prompts import opening_part
from decrack.text import finalize_post

STATEMENT = "decision_statement"


def cand(*cites: str, act: str = "propose") -> Candidate:
    return Candidate(alt_ref="new", alternative="Decorator", act=act, reason="", cites=list(cites))


def every_alias(thread: Thread) -> dict:
    """The alias table of a prompt that shows every sentence of the thread."""
    return build_aliases([(post, 1, len(post.spans)) for post in thread.posts])


def finalized(post_id: str, author: str, sentences: list[str], seq: int = 1) -> Post:
    return finalize_post(Post(id=post_id, seq=seq, author=author, role="participant", text=" ".join(sentences)))


def test_a_valid_cite_becomes_evidence_cut_from_the_post_text(synthetic_thread):
    result = gate_candidates(synthetic_thread, [cand("p2.s1")], every_alias(synthetic_thread))
    assert (result.total, result.dropped) == (1, 0)
    [kept] = result.kept
    post = synthetic_thread.posts[1]
    first = "Why not use a decorator instead of a new keyword?"
    assert kept.evidence == [
        Evidence(
            post_id=post.id,
            post_version=1,
            post_sha256=post.sha256,
            sentence_indexes=[1],
            start=0,
            end=len(first),
            quote=first,
            url=post.url,
            author="bob",
            source_check="valid",
            support="unchecked",
            evidence_type="proposal",
        )
    ]
    assert (kept.post.id, kept.role, kept.author, kept.evidence_type) == (post.id, "participant", "bob", "proposal")
    assert kept.candidate.cites == []  # the stable references live in the evidence; no alias is kept


def test_aliases_resolve_only_inside_the_prompts_alias_table(synthetic_thread):
    posts = synthetic_thread.posts
    window = build_aliases([(posts[1], 1, 2), (posts[2], 1, 2)])
    assert sorted(window) == ["p2.s1", "p2.s2", "p3.s1", "p3.s2"]
    assert window["p3.s2"] == (posts[2], 2)

    # p5.s2 and p8.s2 exist in the thread but were not shown in this prompt; p2.s3 does not exist.
    result = gate_candidates(synthetic_thread, [cand("p5.s2"), cand("p3.s1", "p8.s2"), cand("p2.s3")], window)
    assert (result.total, result.dropped) == (3, 2)
    [kept] = result.kept
    assert [(item.post_id, item.sentence_indexes) for item in kept.evidence] == [(posts[2].id, [1])]
    assert kept.post.id == posts[2].id

    # The header sentences of the opening post are part of every prompt's table.
    with_header = build_aliases([opening_part(synthetic_thread), (posts[5], 1, 2)])
    [kept] = gate_candidates(synthetic_thread, [cand("p1.s2", "p6.s1")], with_header).kept
    assert [(item.post_id, item.sentence_indexes) for item in kept.evidence] == [(posts[0].id, [2]), (posts[5].id, [1])]

    # A table built from posts of another thread resolves nothing here.
    outsider = posts[1].model_copy(update={"id": "dpo:12345:1"})
    result = gate_candidates(synthetic_thread, [cand("p2.s1")], build_aliases([(outsider, 1, 2)]))
    assert (result.kept, result.dropped) == ([], 1)


def test_build_aliases_skips_indexes_outside_the_post(synthetic_thread):
    post = synthetic_thread.posts[1]
    assert sorted(build_aliases([(post, 0, 5)])) == ["p2.s1", "p2.s2"]
    assert build_aliases([(post, 2, 1)]) == {}


def test_invalid_and_malformed_cites_are_dropped(synthetic_thread):
    candidates = [
        cand("p2.s9"),  # post 2 has two sentences
        cand("p2.s0"),
        cand("p99.s1"),  # no such post
        cand("p0.s1"),
        cand("2.1", "post 2", "", "p2", "s1"),
        cand(),
    ]
    result = gate_candidates(synthetic_thread, candidates, every_alias(synthetic_thread))
    assert result.kept == []
    assert (result.total, result.dropped) == (6, 6)


def test_cites_are_normalised(synthetic_thread):
    assert split_cites([" [P2.S1] ", "(p2.s2)", "p2.s1", "p5.s1; p5.s2", "p5.s3,p1.s1"]) == [
        "p2.s1",
        "p2.s2",
        "p5.s1",
        "p5.s2",
        "p5.s3",
        "p1.s1",
    ]
    pairs = resolve_aliases(every_alias(synthetic_thread), [" [P2.S1] ", "p2.s2", "p9.s1", "P2.s1"])
    assert [(post.id, index) for post, index in pairs] == [
        (synthetic_thread.posts[1].id, 1),
        (synthetic_thread.posts[1].id, 2),
    ]


def test_every_quote_is_the_post_text_between_start_and_end(synthetic_thread):
    for post in synthetic_thread.posts:
        for first in range(1, len(post.spans) + 1):
            for last in range(first, len(post.spans) + 1):
                indexes = list(range(first, last + 1))
                item = make_evidence(post, indexes, "objection")
                assert item.quote == post.text[item.start : item.end]
                assert (item.start, item.end) == (post.spans[first - 1].start, post.spans[last - 1].end)
                assert item.quote == " ".join(post.sentences[first - 1 : last])
                assert item.sentence_indexes == indexes
                assert (item.post_id, item.post_version, item.post_sha256) == (post.id, post.version, post.sha256)
                assert (item.url, item.author, item.source_check, item.support) == (
                    post.url,
                    post.author,
                    "valid",
                    "unchecked",
                )
                assert item.evidence_type == "objection"


def test_quotes_follow_the_normalized_text_exactly():
    post = finalized("file:abcd1234:1", "zoe", ["Café “quotes” stay.", "Second  sentence\nhere."])
    assert post.text.startswith("Café ")  # NFC
    first, second = make_evidence(post, [1]), make_evidence(post, [2])
    assert first.quote == "Café “quotes” stay." == post.text[first.start : first.end]
    assert second.quote == "Second  sentence\nhere." == post.text[second.start : second.end]


def test_a_run_must_be_contiguous_and_inside_the_post(synthetic_thread):
    post = synthetic_thread.posts[4]
    for indexes in ([1, 3], [4], [0, 1], []):
        with pytest.raises(ValueError):
            make_evidence(post, indexes)


def test_non_contiguous_cites_become_separate_evidence(synthetic_thread):
    posts = synthetic_thread.posts
    aliases = every_alias(synthetic_thread)
    pairs = resolve_aliases(aliases, ["p5.s3", "p5.s1", "p1.s2", "p5.s2", "p1.s3"])
    evidence = evidence_for(pairs, "decision_statement")
    assert [(item.post_id, item.sentence_indexes) for item in evidence] == [
        (posts[0].id, [2, 3]),
        (posts[4].id, [1, 2, 3]),
    ]
    assert evidence[1].quote == posts[4].text
    assert {item.evidence_type for item in evidence} == {"decision_statement"}

    split = evidence_for(resolve_aliases(aliases, ["p5.s3", "p5.s1"]))
    assert [item.sentence_indexes for item in split] == [[1], [3]]
    assert [item.quote for item in split] == [posts[4].sentences[0], posts[4].sentences[2]]
    assert {item.evidence_type for item in split} == {"other"}
    assert evidence_for([]) == []

    [kept] = gate_candidates(synthetic_thread, [cand("p5.s3", "p5.s1", act="reject")], aliases).kept
    assert [item.sentence_indexes for item in kept.evidence] == [[1], [3]]


def test_the_evidence_type_is_copied_onto_every_evidence_item(synthetic_thread):
    candidate = cand("p8.s2", "p5.s1", "p8.s1", act="reject")  # post 8 says "rejected": a decision cue
    [kept] = gate_candidates(synthetic_thread, [candidate], every_alias(synthetic_thread)).kept
    assert kept.evidence_type == "decision_statement"
    assert [(item.post_id, item.sentence_indexes, item.evidence_type) for item in kept.evidence] == [
        (synthetic_thread.posts[4].id, [1], "decision_statement"),
        (synthetic_thread.posts[7].id, [1, 2], "decision_statement"),
    ]


def test_a_decision_cue_makes_a_decision_statement():
    assert derive_evidence_type("reject", "participant", ["We rejected the decorator approach."]) == STATEMENT
    assert derive_evidence_type("accept", "decider", ["The Steering Council ACCEPTS PEP 9999."]) == STATEMENT
    assert derive_evidence_type("defer", "author", ["No.", "It is added to the Rejected Ideas."]) == STATEMENT
    assert derive_evidence_type("withdraw", "participant", ["We won’t do that."]) == STATEMENT
    assert DECISION_CUES.search("we are not going to") and not DECISION_CUES.search("unaccepted")


def test_without_a_cue_the_evidence_type_follows_the_role_and_act():
    plain = ["I do not like it."]
    assert derive_evidence_type("reject", "author", plain) == "author_position"
    assert derive_evidence_type("accept", "author", plain) == "author_position"
    assert derive_evidence_type("reject", "participant", plain) == "objection"
    assert derive_evidence_type("defer", "decider", plain) == "objection"
    assert derive_evidence_type("accept", "maintainer", plain) == "support"
    # The other acts ignore cues and roles.
    assert derive_evidence_type("propose", "author", ["It was rejected before."]) == "proposal"
    assert derive_evidence_type("object", "decider", ["Rejected."]) == "objection"
    assert derive_evidence_type("support", "participant", plain) == "support"


def test_the_gate_derives_the_evidence_type_from_the_latest_posts_role(synthetic_thread):
    aliases = every_alias(synthetic_thread)
    [author_no_cue] = gate_candidates(synthetic_thread, [cand("p1.s3", act="reject")], aliases).kept
    assert (author_no_cue.role, author_no_cue.evidence_type) == ("author", "author_position")
    [participant_no_cue] = gate_candidates(synthetic_thread, [cand("p3.s1", act="reject")], aliases).kept
    assert participant_no_cue.evidence_type == "objection"
    assert {item.evidence_type for item in participant_no_cue.evidence} == {"objection"}


def test_only_resolved_cites_survive_and_the_model_candidate_is_unchanged(synthetic_thread):
    original = cand("p5.s2", "p9.s1", "nonsense", act="reject")
    [kept] = gate_candidates(synthetic_thread, [original], every_alias(synthetic_thread)).kept
    assert [item.quote for item in kept.evidence] == [
        "We rejected the decorator approach because decorators cannot apply to import statements."
    ]
    assert kept.candidate.cites == []
    assert (kept.candidate.act, kept.candidate.alternative) == ("reject", "Decorator")
    assert original.cites == ["p5.s2", "p9.s1", "nonsense"]


def test_counts(synthetic_thread):
    candidates = [cand("p1.s1"), cand("p42.s1"), cand("p3.s1", "p3.s2"), cand("x"), cand("p7.s2")]
    result = gate_candidates(synthetic_thread, candidates, every_alias(synthetic_thread))
    assert (result.total, result.dropped, len(result.kept)) == (5, 2, 3)
    assert [item.post.seq for item in result.kept] == [1, 3, 7]


def test_an_act_belongs_to_the_latest_cited_post(synthetic_thread):
    posts = synthetic_thread.posts
    result = gate_candidates(
        synthetic_thread,
        [cand("p5.s2", "p2.s1", act="reject"), cand("p8.s2", "p3.s1", act="reject")],
        every_alias(synthetic_thread),
    )
    first, second = result.kept
    assert (first.post.id, first.role, first.author) == (posts[4].id, "author", "alice")
    assert [item.post_id for item in first.evidence] == [posts[1].id, posts[4].id]
    assert (second.post.id, second.role, second.author) == (posts[7].id, "decider", "sam")
    assert [item.post_id for item in second.evidence] == [posts[2].id, posts[7].id]


def test_an_alias_resolves_to_the_same_post_after_a_re_merge_that_shifts_seq():
    first_topic = [
        finalized("dpo:10:100", "alice", ["I propose lazy imports.", "They load on first use."]),
        finalized("dpo:10:101", "bob", ["A flag would be simpler.", "We will not add a flag."]),
    ]
    second_topic = [finalized("dpo:20:200", "carol", ["An earlier topic had this idea.", "It was dropped."])]

    def merged(*posts: Post) -> Thread:
        """A thread of copies of ``posts`` renumbered 1, 2, ... in this order, as a merge does."""
        copies = [post.model_copy(update={"seq": seq}) for seq, post in enumerate(posts, start=1)]
        return Thread(id="pep:1", kind="discourse", posts=copies)

    before = merged(*first_topic)
    after = merged(*second_topic, *first_topic)  # a topic merged in front shifts every seq by one
    target = "dpo:10:101"
    alias_before = sentence_alias(before.post_by_id(target).seq, 2)
    alias_after = sentence_alias(after.post_by_id(target).seq, 2)
    assert (alias_before, alias_after) == ("p2.s2", "p3.s2")

    [(post_before, index_before)] = resolve_aliases(every_alias(before), [alias_before])
    [(post_after, index_after)] = resolve_aliases(every_alias(after), [alias_after])
    assert (post_before.id, post_before.version, index_before) == (post_after.id, post_after.version, index_after)
    assert (post_after.id, index_after) == (target, 2)
    # Evidence holds no alias and no seq, so both runs store the same citation.
    assert make_evidence(post_before, [index_before]) == make_evidence(post_after, [index_after])
    assert make_evidence(post_after, [index_after]).quote == "We will not add a flag."

    # The old alias means another sentence after the re-merge: aliases are only valid within one run.
    [(other, index)] = resolve_aliases(every_alias(after), [alias_before])
    assert (other.id, index) == ("dpo:10:100", 2)
