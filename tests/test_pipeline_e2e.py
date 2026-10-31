"""compile_thread end to end with scripted model answers: the synthetic PEP thread, and MAP cache keys."""

from __future__ import annotations

import re

import pytest

from decrack import __version__
from decrack.config import Settings
from decrack.models import SCHEMA_VERSION, CodeLink, DecidedBy, DecisionRecord, Post, Thread, make_record_id
from decrack.pipeline import run as run_module
from decrack.pipeline.extract import map_request_key
from decrack.pipeline.llm import LLMError, ScriptedLLM
from decrack.pipeline.prompts import MAP_SYSTEM, PROMPT_VERSION, render_post
from decrack.pipeline.run import compile_thread
from decrack.pipeline.support import claims_for
from decrack.pipeline.windows import make_windows, part_ref
from decrack.text import estimate_tokens, finalize_post

# (post the item is about, alternative, act, evidence_type, reason, cites) as a model would label the thread.
# The model is no longer asked for evidence_type; the extra key is ignored, and the gate derives its own.
ITEMS = [
    (1, "Hard lazy keyword", "propose", "proposal", "", ["p1.s2"]),
    (
        2,
        "Use a decorator instead of a new keyword",
        "propose",
        "proposal",
        "A decorator would avoid adding new syntax.",
        ["p2.s1", "p2.s2"],
    ),
    (
        3,
        "Hard lazy keyword",
        "object",
        "objection",
        "It breaks existing code that uses lazy as a name.",
        ["p3.s1", "p3.s2"],
    ),
    (4, "Global flag to enable laziness everywhere", "propose", "proposal", "", ["p4.s1", "p4.s2"]),
    # One real cite in odd case plus one cite of a post that does not exist.
    (
        5,
        "Use a decorator instead of a new keyword",
        "reject",
        "decision_statement",
        "Decorators cannot apply to import statements.",
        ["P5.S2", "p9.s1"],
    ),
    (
        5,
        "Global flag to enable laziness everywhere",
        "reject",
        "decision_statement",
        "It changes behaviour for every library at once.",
        ["[p5.s3]"],
    ),
    (
        6,
        "Global flag to enable laziness everywhere",
        "object",
        "objection",
        "It would break libraries that rely on import side effects.",
        ["p6.s1", "p6.s2"],
    ),
    (7, "Soft keyword", "propose", "proposal", "It keeps lazy usable as a normal name.", ["p7.s1", "p7.s2"]),
    (8, "Soft keyword", "accept", "decision_statement", "", ["p8.s1"]),
    (8, "Hard lazy keyword", "reject", "decision_statement", "It breaks existing code.", ["p8.s2"]),
    # Only bogus cites: the gate must drop it.
    (8, "Make widgets eager by default", "propose", "proposal", "", ["p42.s1", "s3"]),
]

# key, title, status, status_kind, basis, seq of the status post, decided_by (handle, role)
SAM, ALICE = ("sam", "decider"), ("alice", "author")
EXPECTED = [
    ("A1", "Hard lazy keyword", "rejected", "confirmed", "decider_statement", 8, SAM),
    ("A2", "Use a decorator instead of a new keyword", "rejected", "confirmed", "author_statement", 5, ALICE),
    ("A3", "Global flag to enable laziness everywhere", "rejected", "confirmed", "author_statement", 5, ALICE),
    ("A4", "Soft keyword", "accepted", "confirmed", "decider_statement", 8, SAM),
]


def map_item(
    alternative: str, act: str, evidence_type: str, reason: str, cites: list[str], alt_ref: str = "new"
) -> dict:
    return {
        "alt_ref": alt_ref,
        "alternative": alternative,
        "act": act,
        "evidence_type": evidence_type,
        "reason": reason,
        "cites": cites,
    }


ALL_ITEMS = {"items": [map_item(*row[1:]) for row in ITEMS]}


def windowed_map(messages: list[dict]) -> dict:
    """Answer like a model that labels only its window's posts and refers to known alternatives by key."""
    content = messages[1]["content"]
    present = {int(number) for number in re.findall(r'<post n="(\d+)"', content)}
    known = {title: key for key, title in re.findall(r"^(A\d+): (.+?)(?: — .*)?$", content, flags=re.MULTILINE)}
    return {"items": [map_item(*row[1:], alt_ref=known.get(row[1], "new")) for row in ITEMS if row[0] in present]}


def support_reply(messages: list[dict]) -> dict:
    """Every claim of the batch is supported."""
    numbers = re.findall(r"^Claim (\d+): ", messages[1]["content"], flags=re.MULTILINE)
    return {"results": [{"id": int(number), "verdict": "supported"} for number in numbers]}


def scripted(map_answer, support: bool = False) -> ScriptedLLM:
    """MAP answers from ``map_answer`` and, optionally, "supported" for every claim."""
    responses = {"map": map_answer}
    if support:
        responses["support"] = support_reply
    return ScriptedLLM(responses)


@pytest.fixture
def links(monkeypatch):
    """Fixed code links (with a repeat) instead of whatever linking finds in the test threads."""
    mentioned = CodeLink(repo="example/widgets", path="Lib/widgets.py", method="mentioned", strength="direct")
    pr_file = CodeLink(repo="example/widgets", path="Lib/widgets.py", pr=42, method="pr_files", strength="historical")
    monkeypatch.setattr(run_module, "mentioned_links", lambda thread: [mentioned, mentioned.model_copy()])
    monkeypatch.setattr(run_module, "pr_file_links", lambda thread: [pr_file])
    return [mentioned, pr_file]


def all_evidence(record: DecisionRecord) -> list:
    """Every Evidence of the record: options, their reasons and their status events."""
    found = []
    for option in record.options:
        found += option.evidence
        found += [item for reason in option.reasons for item in reason.evidence]
        found += [item for event in option.status_history for item in event.evidence]
    return found


def check_quotes(thread: Thread, record: DecisionRecord) -> None:
    """Every quote is text[start:end] of the cited post version, from one sentence's start to another's end."""
    for option in record.options:
        assert option.evidence
    for evidence in all_evidence(record):
        post = thread.post_by_id(evidence.post_id)
        assert post is not None
        assert evidence.quote == post.text[evidence.start : evidence.end]
        indexes = evidence.sentence_indexes
        assert indexes == list(range(indexes[0], indexes[0] + len(indexes)))
        assert (evidence.start, evidence.end) == (post.spans[indexes[0] - 1].start, post.spans[indexes[-1] - 1].end)
        assert (evidence.post_version, evidence.post_sha256, evidence.url, evidence.source_check) == (
            post.version,
            post.sha256,
            post.url,
            "valid",
        )


def seq_of(thread: Thread, post_id: str | None) -> int | None:
    post = thread.post_by_id(post_id) if post_id else None
    return post.seq if post else None


def history(thread: Thread, option) -> list[tuple]:
    return [
        (seq_of(thread, event.post_id), event.act, event.role, event.evidence_type, event.status_after)
        for event in option.status_history
    ]


def test_compile_thread_end_to_end(synthetic_thread, links):
    posts = synthetic_thread.posts
    llm = scripted([ALL_ITEMS])
    notes: list[str] = []
    record = compile_thread(synthetic_thread, llm, Settings(), progress=notes.append)

    # With the defaults the model does one job: one MAP call for the one window.
    assert [step for step, _ in llm.requests] == ["map"]
    assert llm.requests[0][1][0] == {"role": "system", "content": MAP_SYSTEM}
    assert llm.key_extras[0] == {
        "digest": "",
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "window": [[post.id, post.version, post.sha256, 1, len(post.spans)] for post in posts],
        "known": [],
        "chain": "",
    }
    assert [
        (
            option.key,
            option.title,
            option.status,
            option.status_kind,
            option.status_basis,
            seq_of(synthetic_thread, option.status_post),
            (option.decided_by.handle, option.decided_by.role),
        )
        for option in record.options
    ] == EXPECTED
    assert [option.confidence for option in record.options] == ["high"] * 4

    # Evidence types are derived in code: posts 5 and 8 say "rejected"/"accepts", so they are decision statements.
    hard, decorator, flag, soft = record.options
    assert history(synthetic_thread, hard) == [
        (1, "propose", "author", "proposal", "proposed"),
        (3, "object", "participant", "objection", "unresolved"),
        (8, "reject", "decider", "decision_statement", "rejected"),
    ]
    assert history(synthetic_thread, decorator) == [
        (2, "propose", "participant", "proposal", "proposed"),
        (5, "reject", "author", "decision_statement", "rejected"),
    ]
    assert history(synthetic_thread, flag) == [
        (4, "propose", "maintainer", "proposal", "proposed"),
        (5, "reject", "author", "decision_statement", "rejected"),
        (6, "object", "participant", "objection", "rejected"),
    ]
    assert history(synthetic_thread, soft) == [
        (7, "propose", "participant", "proposal", "proposed"),
        (8, "accept", "decider", "decision_statement", "accepted"),
    ]
    for option in record.options:
        for event in option.status_history:
            assert event.evidence
            assert {item.evidence_type for item in event.evidence} == {event.evidence_type}
    # "P5.S2" resolved and "p9.s1" was dropped.
    assert [item.sentence_indexes for item in decorator.status_history[1].evidence] == [[2]]

    # Reasons are the MAP reasons; the accept without one falls back to its quote.
    def cited(reason) -> list[tuple]:
        return [(seq_of(synthetic_thread, item.post_id), item.sentence_indexes) for item in reason.evidence]

    reasons = [[(reason.stance, reason.text, cited(reason)) for reason in option.reasons] for option in record.options]
    assert reasons == [
        [
            ("con", "It breaks existing code that uses lazy as a name.", [(3, [1, 2])]),
            ("con", "It breaks existing code.", [(8, [2])]),
        ],
        [
            ("pro", "A decorator would avoid adding new syntax.", [(2, [1, 2])]),
            ("con", "Decorators cannot apply to import statements.", [(5, [2])]),
        ],
        [
            ("con", "It changes behaviour for every library at once.", [(5, [3])]),
            ("con", "It would break libraries that rely on import side effects.", [(6, [1, 2])]),
        ],
        [
            ("pro", "It keeps lazy usable as a normal name.", [(7, [1, 2])]),
            ("pro", "The Steering Council accepts PEP 9999 with the soft keyword.", [(8, [1])]),
        ],
    ]

    # The support check is off by default: every claim and evidence item stays "unchecked".
    assert all(event.support == "unchecked" for option in record.options for event in option.status_history)
    assert all(reason.support == "unchecked" for option in record.options for reason in option.reasons)
    assert all(item.support == "unchecked" for item in all_evidence(record))
    check_quotes(synthetic_thread, record)

    assert record.id == make_record_id("pep:9999")
    assert (record.thread_id, record.thread_url) == ("pep:9999", synthetic_thread.url)
    assert record.question == "PEP 9999: Lazy widgets"
    assert record.outcome == "4 options: 1 accepted, 3 rejected"
    assert record.decided_by == DecidedBy(handle="sam", role="decider")
    assert record.decided_in_post == posts[7].id
    assert record.verification == "unverified"  # support did not run
    assert record.code_links == links

    run = record.run
    assert (run.mode, run.model, run.model_digest, run.ollama_version) == ("scripted", "scripted", "", "")
    assert (run.prompt_version, run.schema_version) == (PROMPT_VERSION, SCHEMA_VERSION)
    assert run.decrack_version == __version__
    assert run.params == {
        "num_ctx": 8192,
        "temperature": 0,
        "think": False,
        "window_max_tokens": 3000,
        "window_overlap_tokens": 300,
        "support_check": False,
    }
    assert (run.windows, run.candidates_total, run.candidates_verified, run.llm_calls) == (1, 11, 10, 1)
    assert (run.cache_hits, run.tokens_in, run.tokens_out, run.support_checked) == (0, 0, 0, False)
    assert run.started_at.tzinfo is not None
    assert run.seconds >= 0
    # Every alias shown maps to a stable (post id, version, sentence index); every post shown is allowlisted.
    assert {alias: (target.post_id, target.version, target.index) for alias, target in run.alias_map.items()} == {
        f"p{post.seq}.s{span.index}": (post.id, post.version, span.index) for post in posts for span in post.spans
    }
    assert [(ref.post_id, ref.version, ref.sha256) for ref in run.source_allowlist] == [
        (post.id, post.version, post.sha256) for post in posts
    ]
    assert notes  # progress was reported


def test_with_the_support_check_every_supported_claim_stays_confirmed(synthetic_thread, links):
    settings = Settings(support_check=True)
    llm = scripted([ALL_ITEMS], support=True)
    record = compile_thread(synthetic_thread, llm, settings)

    batches = -(-len(claims_for(record.options)) // settings.support_batch_size)
    assert [step for step, _ in llm.requests] == ["map"] + ["support"] * batches
    assert [
        (option.key, option.title, option.status, option.status_kind, option.status_basis, option.confidence)
        for option in record.options
    ] == [(key, title, status, kind, basis, "high") for key, title, status, kind, basis, _, _ in EXPECTED]
    assert all(event.support == "supported" for option in record.options for event in option.status_history)
    assert all(reason.support == "supported" for option in record.options for reason in option.reasons)
    assert all(item.support == "supported" for item in all_evidence(record))
    check_quotes(synthetic_thread, record)
    assert record.verification == "machine_checked"
    assert record.decided_by == DecidedBy(handle="sam", role="decider")
    assert (record.run.support_checked, record.run.params["support_check"]) == (True, True)


def test_compile_thread_over_several_windows(synthetic_thread, links):
    # Room for two of the largest posts: no post is split, and the thread needs several windows.
    costs = [estimate_tokens(render_post(post, synthetic_thread)) for post in synthetic_thread.posts]
    settings = Settings(
        window_max_tokens=2 * max(costs),
        window_overlap_tokens=0,
    )
    windows = make_windows(synthetic_thread, settings.window_max_tokens, settings.window_overlap_tokens)
    assert len(windows) >= 3
    parts = [part for window in windows for part in window.parts]
    assert all((part.first_index, part.last_index) == (1, len(part.post.sentences)) for part in parts)

    llm = ScriptedLLM({"map": windowed_map})
    record = compile_thread(synthetic_thread, llm, settings)

    # One MAP call per window, each keyed by its own parts and chained to the window before.
    assert [step for step, _ in llm.requests] == ["map"] * len(windows)
    for window, extra in zip(windows, llm.key_extras, strict=True):
        assert extra["window"] == [part_ref(part) for part in window.parts]
    keys = [map_request_key(messages, extra) for (_, messages), extra in zip(llm.requests, llm.key_extras)]
    assert [extra["chain"] for extra in llm.key_extras] == [""] + keys[:-1]

    # Later windows see the alternatives found so far.
    assert llm.key_extras[0]["known"] == []
    assert "Known alternatives:\nnone yet" in llm.requests[0][1][1]["content"]
    assert [row[:2] for row in llm.key_extras[-1]["known"][:3]] == [
        ["A1", "Hard lazy keyword"],
        ["A2", "Use a decorator instead of a new keyword"],
        ["A3", "Global flag to enable laziness everywhere"],
    ]
    assert "\nA1: Hard lazy keyword" in llm.requests[-1][1][1]["content"]

    assert [
        (option.key, option.title, option.status, option.status_kind, option.status_basis) for option in record.options
    ] == [(key, title, status, kind, basis) for key, title, status, kind, basis, _, _ in EXPECTED]
    # Posts read by two windows give their acts once.
    acts = [[(seq_of(synthetic_thread, e.post_id), e.act) for e in option.status_history] for option in record.options]
    assert acts == [
        [(1, "propose"), (3, "object"), (8, "reject")],
        [(2, "propose"), (5, "reject")],
        [(4, "propose"), (5, "reject"), (6, "object")],
        [(7, "propose"), (8, "accept")],
    ]
    decorator = record.options[1]
    assert [(reason.stance, reason.text) for reason in decorator.reasons] == [
        ("pro", "A decorator would avoid adding new syntax."),
        ("con", "Decorators cannot apply to import statements."),
    ]
    check_quotes(synthetic_thread, record)

    present = [{part.post.seq for part in window.parts} for window in windows]
    answered = sum(1 for seqs in present for row in ITEMS if row[0] in seqs)
    bogus = sum(1 for seqs in present if 8 in seqs)  # the eager-widgets item cites nothing real
    run = record.run
    assert (run.windows, run.llm_calls, run.candidates_total, run.candidates_verified) == (
        len(windows),
        len(windows),
        answered,
        answered - bogus,
    )
    assert len(run.alias_map) == sum(len(post.spans) for post in synthetic_thread.posts)


def test_an_invalid_map_answer_skips_the_window(synthetic_thread, links):
    llm = ScriptedLLM({"map": [{"items": "garbage"}]})
    notes: list[str] = []
    record = compile_thread(synthetic_thread, llm, Settings(), progress=notes.append)
    assert record.options == []
    assert record.outcome == "No options with verified evidence were found."
    assert record.verification == "unverified"
    assert (record.decided_by, record.decided_in_post) == (None, None)
    assert (record.run.windows, record.run.candidates_total, record.run.llm_calls) == (1, 0, 1)
    assert len(record.run.alias_map) == 18  # the prompt was shown, so its aliases are on record
    assert any("skipped" in note for note in notes)


def test_other_model_errors_stop_the_run(synthetic_thread, links):
    with pytest.raises(LLMError):
        compile_thread(synthetic_thread, ScriptedLLM(), Settings())


# MAP cache keys across runs


def keyed_thread(count: int) -> Thread:
    """Up to 9 posts of four sentences that all render to the same length."""
    posts = []
    for seq in range(1, count + 1):
        sentences = [
            f"Alpha {seq} says one thing.",
            f"Bravo {seq} says two things.",
            f"Charlie {seq} says three.",
            f"Delta {seq} says four.",
        ]
        post = Post(
            id=f"file:abcd1234:{seq}",
            source_id="file:abcd1234",
            source_post_number=seq,
            seq=seq,
            author=f"u{seq}",
            role="participant",
            text=" ".join(sentences),
        )
        posts.append(finalize_post(post))
    return Thread(id="file:abcd1234", kind="file", title="Keys", posts=posts)


def key_settings(thread: Thread) -> Settings:
    """Windows of three posts with one post of overlap; MAP is the only model step."""
    cost = estimate_tokens(render_post(thread.posts[0], thread))
    return Settings(
        window_max_tokens=3 * cost,
        window_overlap_tokens=cost,
    )


def window_seqs(thread: Thread, settings: Settings) -> list[list[int]]:
    windows = make_windows(thread, settings.window_max_tokens, settings.window_overlap_tokens)
    return [[part.post.seq for part in window.parts] for window in windows]


def map_keys(thread: Thread, settings: Settings) -> tuple[list[str], ScriptedLLM]:
    """Compile with a model that finds nothing; return the key of each MAP call and the LLM."""
    llm = ScriptedLLM({"map": lambda messages: {"items": []}})
    compile_thread(thread, llm, settings)
    assert [step for step, _ in llm.requests] == ["map"] * len(llm.requests)
    return [map_request_key(messages, extra) for (_, messages), extra in zip(llm.requests, llm.key_extras)], llm


def test_appending_a_post_changes_only_the_last_windows_map_key(links):
    thread = keyed_thread(6)
    settings = key_settings(thread)
    assert window_seqs(thread, settings) == [[1, 2, 3], [3, 4, 5], [5, 6]]
    keys, llm = map_keys(thread, settings)
    assert len(set(keys)) == 3
    assert [extra["chain"] for extra in llm.key_extras] == ["", keys[0], keys[1]]

    longer = keyed_thread(7)
    assert window_seqs(longer, settings) == [[1, 2, 3], [3, 4, 5], [5, 6, 7]]
    new_keys, _ = map_keys(longer, settings)
    assert new_keys[:2] == keys[:2]
    assert new_keys[2] != keys[2]


def test_editing_the_first_post_changes_every_later_map_key_through_the_chain(links):
    thread = keyed_thread(6)
    settings = key_settings(thread)
    keys, llm = map_keys(thread, settings)

    edited = keyed_thread(6)
    first = edited.posts[0]
    first.text = first.text.replace("four", "FOUR")  # the 4th sentence: same length, and not in the header
    finalize_post(first)
    assert first.sha256 != thread.posts[0].sha256
    assert window_seqs(edited, settings) == window_seqs(thread, settings) == [[1, 2, 3], [3, 4, 5], [5, 6]]
    new_keys, new_llm = map_keys(edited, settings)
    assert len(new_keys) == 3
    assert all(new != old for new, old in zip(new_keys, keys))

    # Windows 2 and 3 do not hold post 1: their messages and parts are the same, only the chain differs.
    for index in (1, 2):
        old_messages, new_messages = llm.requests[index][1], new_llm.requests[index][1]
        old_extra, new_extra = llm.key_extras[index], new_llm.key_extras[index]
        assert new_messages == old_messages
        assert {**new_extra, "chain": ""} == {**old_extra, "chain": ""}
        assert new_extra["chain"] == new_keys[index - 1] != old_extra["chain"]
        assert map_request_key(new_messages, {**new_extra, "chain": old_extra["chain"]}) == keys[index]
