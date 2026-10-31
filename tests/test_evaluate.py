"""Withheld-PEP evaluation: gold files, fuzzy matching, status kinds, the closed-book baseline and a full run."""

from __future__ import annotations

import json
from pathlib import Path

from decrack.config import Settings
from decrack.evaluate import (
    MATCH_THRESHOLD,
    SEARCH_K,
    OptionIndex,
    closed_book,
    closed_book_recall,
    content_tokens,
    find_gold,
    load_gold,
    macro_average,
    matched_entries,
    option_search_text,
    render_summary,
    run_eval,
    score_record,
    search_recall,
    similarity,
)
from decrack.models import DecisionRecord, GoldFile, GoldItem, Option, Reason
from decrack.pipeline.llm import ScriptedLLM


def make_gold() -> GoldFile:
    """Two ideas the sample record rejected, and one the thread never discussed."""
    return GoldFile(
        pep=9999,
        title="Lazy widgets",
        items=[
            GoldItem(
                id="pep9999-r1",
                idea="Using a decorator instead of a keyword",
                reason="Decorators cannot apply to import statements.",
            ),
            GoldItem(
                id="pep9999-r2",
                idea="A global laziness flag",
                reason="It would change the behaviour of every library at once.",
            ),
            GoldItem(
                id="pep9999-r3",
                idea="Ship widgets as a separate PyPI package",
                reason="Packaging is out of scope for the standard library.",
                recoverable=False,
            ),
        ],
    )


def with_kinds(record: DecisionRecord, kinds: dict[str, str]) -> DecisionRecord:
    """A copy of ``record`` whose options listed in ``kinds`` (by key) get that status kind."""
    options = [
        option.model_copy(update={"status_kind": kinds.get(option.key, option.status_kind)})
        for option in record.options
    ]
    return record.model_copy(update={"options": options})


def fake_map(messages: list[dict]) -> dict:
    """A MAP answer that cites real sentence aliases of the synthetic thread."""
    return {
        "items": [
            {
                "alt_ref": "new",
                "alternative": "Use a decorator instead of a new keyword",
                "act": "propose",
                "evidence_type": "proposal",
                "reason": "",
                "cites": ["p2.s1"],
            },
            {
                "alt_ref": "new",
                "alternative": "Use a decorator instead of a new keyword",
                "act": "reject",
                "evidence_type": "decision_statement",
                "reason": "Decorators cannot apply to import statements.",
                "cites": ["p5.s2"],
            },
            {
                "alt_ref": "new",
                "alternative": "Global flag to enable laziness everywhere",
                "act": "propose",
                "evidence_type": "proposal",
                "reason": "",
                "cites": ["p4.s1"],
            },
            {
                "alt_ref": "new",
                "alternative": "Global flag to enable laziness everywhere",
                "act": "reject",
                "evidence_type": "decision_statement",
                "reason": "It changes behaviour for every library at once.",
                "cites": ["p5.s3"],
            },
            {
                "alt_ref": "new",
                "alternative": "Soft keyword",
                "act": "accept",
                "evidence_type": "decision_statement",
                "reason": "It keeps lazy usable as a normal name.",
                "cites": ["p8.s1"],
            },
        ]
    }


def test_similarity_and_content_tokens():
    assert similarity("Using sys.excepthook", "using sys excepthook!") == 1.0
    assert similarity("", "anything") == 0.0
    assert content_tokens("Why not use the new keyword?") == {"new", "keyword"}
    assert similarity("Global flag to enable laziness", "Soft keyword") < MATCH_THRESHOLD


def test_find_and_load_gold(tmp_path):
    gold = make_gold()
    (tmp_path / "pep-0830.json").write_text(gold.model_dump_json(), encoding="utf-8")
    (tmp_path / "pep-77.json").write_text(gold.model_dump_json(), encoding="utf-8")
    assert find_gold(tmp_path, 830) == tmp_path / "pep-0830.json"
    assert find_gold(tmp_path, 77) == tmp_path / "pep-77.json"
    assert find_gold(tmp_path, 1) is None
    assert load_gold(tmp_path / "pep-0830.json") == gold


def test_repository_gold_files_load():
    gold_dir = Path(__file__).resolve().parents[1] / "eval" / "gold"
    path = find_gold(gold_dir, 830)
    assert path is not None
    gold = load_gold(path)
    assert gold.pep == 830
    assert gold.items and all(item.idea for item in gold.items)


def test_score_record_matches_rejected_options(sample_record):
    # Every option of the sample record is confirmed; A1, A2 and A4 are rejected.
    scores = score_record(make_gold(), sample_record)
    assert scores["pep"] == 9999
    assert (scores["gold_total"], scores["gold_recoverable"]) == (3, 2)
    assert (scores["predicted_options"], scores["predicted_rejected"]) == (4, 3)
    assert scores["matched"] == 2
    assert scores["recall_recoverable"] == 1.0
    assert scores["precision_strict"] == 0.667  # 2 of the 3 rejected options are in the gold set
    assert scores["predicted_by_kind"] == {"confirmed": 3, "inferred": 0}
    assert scores["matched_by_kind"] == {"confirmed": 2, "inferred": 0}
    assert scores["precision_by_kind"] == {"confirmed": 0.667, "inferred": None}  # no inferred predictions
    assert scores["reason_agreement"] == 1.0
    assert scores["evidence_backed_recall"] == 1.0
    assert scores["matched_outside_post1"] == 2
    assert scores["recall_any_status"] == 1.0
    assert scores["matching"] == "similarity"

    pairs = {pair["gold_id"]: pair for pair in scores["matches"]}
    assert [pair["gold_id"] for pair in scores["matches"]] == ["pep9999-r1", "pep9999-r2", "pep9999-r3"]
    assert (pairs["pep9999-r1"]["option_key"], pairs["pep9999-r1"]["matched"]) == ("A1", True)
    assert (pairs["pep9999-r2"]["option_key"], pairs["pep9999-r2"]["matched"]) == ("A2", True)
    assert pairs["pep9999-r1"]["status_kind"] == "confirmed"
    assert pairs["pep9999-r1"]["score"] >= MATCH_THRESHOLD
    assert pairs["pep9999-r3"]["matched"] is False
    assert pairs["pep9999-r3"]["recoverable"] is False


def test_evidence_outside_the_opening_post(sample_record, synthetic_thread):
    """Post 1 is found from the thread, else from the run's alias p1.s1; unknown without either."""
    opening = synthetic_thread.posts[0].id
    assert sample_record.run.alias_map["p1.s1"].post_id == opening
    assert score_record(make_gold(), sample_record, thread=synthetic_thread)["matched_outside_post1"] == 2
    assert score_record(make_gold(), sample_record)["matched_outside_post1"] == 2
    assert score_record(make_gold(), sample_record.model_copy(update={"run": None}))["matched_outside_post1"] is None

    # A1 keeps only its quote from post 1 (by id, whatever its position): its match no longer counts.
    first = sample_record.options[0]
    quote = sample_record.options[3].evidence[0]  # A4's quote of post 1
    assert quote.post_id == opening
    only_post1 = first.model_copy(update={"evidence": [quote], "reasons": []})
    record = sample_record.model_copy(update={"options": [only_post1, *sample_record.options[1:]]})
    assert score_record(make_gold(), record, thread=synthetic_thread)["matched_outside_post1"] == 1


def test_precision_by_status_kind(sample_record):
    scores = score_record(make_gold(), with_kinds(sample_record, {"A2": "inferred", "A4": "inferred"}))
    assert scores["predicted_rejected"] == 3
    assert scores["predicted_by_kind"] == {"confirmed": 1, "inferred": 2}
    assert scores["matched_by_kind"] == {"confirmed": 1, "inferred": 1}  # A1 and A2 match; A4 does not
    assert scores["precision_by_kind"] == {"confirmed": 1.0, "inferred": 0.5}
    assert scores["precision_strict"] == 0.667

    # A contested rejection is not a prediction, though recall_any_status still finds it.
    contested = score_record(make_gold(), with_kinds(sample_record, {"A2": "contested", "A4": "inferred"}))
    assert contested["predicted_rejected"] == 2
    assert contested["predicted_by_kind"] == {"confirmed": 1, "inferred": 1}
    assert contested["precision_by_kind"] == {"confirmed": 1.0, "inferred": 0.0}
    assert (contested["matched"], contested["recall_recoverable"], contested["recall_any_status"]) == (1, 0.5, 1.0)

    unresolved = score_record(make_gold(), with_kinds(sample_record, {"A1": "unresolved", "A2": "unresolved"}))
    assert unresolved["predicted_rejected"] == 1  # only A4
    assert unresolved["matched"] == 0


def test_recall_any_status_counts_other_statuses():
    record = DecisionRecord(
        id="dr-test",
        thread_id="file:notes",
        question="How should settings load?",
        outcome="2 options: 1 accepted, 1 rejected",
        options=[
            Option(key="A1", title="Cache the parsed config in a module global", status="accepted"),
            Option(
                key="A2",
                title="Read settings from environment variables",
                status="rejected",
                status_kind="inferred",
            ),
        ],
    )
    gold = GoldFile(
        pep=1,
        items=[
            GoldItem(id="g1", idea="Cache the parsed config in a module global"),
            GoldItem(id="g2", idea="Read settings from environment variables"),
        ],
    )
    scores = score_record(gold, record)
    assert scores["matched"] == 1
    assert scores["recall_recoverable"] == 0.5
    assert scores["recall_any_status"] == 1.0  # g1 was recovered, but as accepted
    assert scores["precision_strict"] == 1.0
    assert scores["precision_by_kind"] == {"confirmed": None, "inferred": 1.0}
    assert scores["evidence_backed_recall"] == 0.0  # no quotes at all
    assert scores["reason_agreement"] == 0.0  # the gold item gives no reason
    assert scores["matched_outside_post1"] is None  # no thread and no run to say which post opened it


def test_closed_book_sees_only_the_number_and_title():
    ideas = [
        {"idea": "Decorator instead of a keyword", "reason": "Decorators cannot apply to import statements."},
        {"idea": "  ", "reason": "An idea without a name is dropped."},
    ]
    llm = ScriptedLLM({"closed_book": [{"ideas": ideas}]})
    found = closed_book(llm, 9999, "Lazy widgets")
    assert found == [ideas[0]]
    [(step, messages)] = llm.requests
    assert step == "closed_book"
    assert messages[-1]["content"] == "PEP 9999: Lazy widgets"
    assert closed_book_recall(make_gold(), found) == 0.5


def test_macro_average_leaves_out_the_control():
    rows = [
        {"pep": 830, "posts": 29, "matched": 3, "recall_recoverable": 0.5, "precision_strict": 0.25},
        {"pep": 810, "posts": 464, "matched": 9, "recall_recoverable": 1.0, "precision_strict": 0.75},
        {"pep": 1, "error": "no gold file", "posts": 3},
    ]
    macro = macro_average(rows)
    assert macro["peps"] == [830]
    assert (macro["posts"], macro["matched"], macro["recall_recoverable"]) == (29, 3, 0.5)
    assert macro["closed_book_recall"] is None
    assert macro["predicted_by_kind"] == {"confirmed": 0, "inferred": 0}
    assert macro["precision_by_kind"] == {"confirmed": None, "inferred": None}


def test_macro_average_of_the_status_kinds():
    rows = [
        {
            "pep": 830,
            "predicted_by_kind": {"confirmed": 2, "inferred": 1},
            "precision_by_kind": {"confirmed": 1.0, "inferred": 0.0},
        },
        {
            "pep": 799,
            "predicted_by_kind": {"confirmed": 0, "inferred": 4},
            "precision_by_kind": {"confirmed": None, "inferred": 0.5},
        },
    ]
    macro = macro_average(rows)
    assert macro["predicted_by_kind"] == {"confirmed": 2, "inferred": 5}
    # A kind with no predictions in a PEP is left out of that kind's mean.
    assert macro["precision_by_kind"] == {"confirmed": 1.0, "inferred": 0.25}


def test_summary_names_the_model_and_digest():
    row = {
        "pep": 830,
        "posts": 29,
        "predicted_options": 5,
        "predicted_rejected": 3,
        "predicted_by_kind": {"confirmed": 2, "inferred": 1},
        "precision_by_kind": {"confirmed": 1.0, "inferred": 0.0},
        "gold_total": 13,
        "gold_recoverable": 13,
        "matched": 2,
        "recall_recoverable": 0.154,
        "precision_strict": 0.667,
    }
    summary = {
        "model": "qwen3.5:4b",
        "model_digest": "sha256:abc123",
        "ollama_version": "0.12.6",
        "mode": "live",
        "prompt_version": "decrack-prompts-2",
        "matching": "similarity",
        "match_threshold": MATCH_THRESHOLD,
        "peps": [row],
        "macro": macro_average([row]),
    }
    text = render_summary(summary)
    assert "`qwen3.5:4b` (digest `sha256:abc123`) in local Ollama 0.12.6" in text
    assert f"deterministic fuzzy matching (difflib + word overlap), threshold {MATCH_THRESHOLD}" in text
    assert "`pep-NNNN/matches.json`" in text
    assert "run mode `live`" in text
    assert "Not a live model run" not in text
    assert "| 830 | 29 | 5 | 3 (2 / 1) | 13 (13) | 2 | 0.154 | 0.667 | 1.000 | 0.000 |" in text
    assert "Not a live model run" in render_summary({**summary, "mode": "replay"})


def test_run_eval_writes_the_runs_layout(tmp_path, synthetic_thread, store):
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()
    (gold_dir / "pep-9999.json").write_text(make_gold().model_dump_json(indent=2), encoding="utf-8")
    out_dir = tmp_path / "examples" / "runs"
    # Neither the thread's title nor its meta may reach the closed-book prompt: only the gold title does.
    synthetic_thread.title = "Lazy widgets, the discussion"
    synthetic_thread.meta["pep_title"] = "A title from the thread meta"
    loaded = []

    def loader(ref: str, settings: Settings):
        loaded.append((ref, settings.eval_mode))
        return synthetic_thread

    closed = {"ideas": [{"idea": "Decorator instead of a keyword", "reason": "Decorators cannot apply to imports."}]}
    llm = ScriptedLLM({"map": fake_map, "closed_book": [closed]})
    messages: list[str] = []
    summary = run_eval(
        [9999],
        gold_dir,
        out_dir,
        # Only "map" and "closed_book" are scripted: the optional support check is off.
        Settings(support_check=False),
        llm,
        store,
        closed_book_baseline=True,
        progress=messages.append,
        loader=loader,
    )

    assert loaded == [("pep:9999", True)]  # the leak guard is on while loading
    assert {step for step, _ in llm.requests} == {"map", "closed_book"}  # matching never calls the model
    [closed_request] = [request for step, request in llm.requests if step == "closed_book"]
    assert closed_request[-1]["content"] == "PEP 9999: Lazy widgets"

    folder = out_dir / "pep-9999"
    for name in ("thread.json", "records.json", "run.json", "scores.json", "matches.json"):
        assert (folder / name).is_file()
    records = json.loads((folder / "records.json").read_text(encoding="utf-8"))
    assert isinstance(records, list) and records[0]["thread_id"] == "pep:9999"
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert run == records[0]["run"]
    assert (run["mode"], run["model"]) == ("scripted", "scripted")

    scores = json.loads((folder / "scores.json").read_text(encoding="utf-8"))
    assert scores["pep"] == 9999
    assert (scores["gold_total"], scores["gold_recoverable"], scores["posts"]) == (3, 2, 8)
    # With the support check off, the author's rejections cite sentences with a decision cue: confirmed.
    assert scores["predicted_rejected"] == 2
    assert scores["predicted_by_kind"] == {"confirmed": 2, "inferred": 0}
    assert scores["precision_by_kind"] == {"confirmed": 1.0, "inferred": None}
    assert scores["matched_outside_post1"] == 2
    assert (scores["model"], scores["mode"]) == ("scripted", "scripted")
    assert scores["closed_book_recall"] == 0.5
    assert (scores["search_recall_at_5"], scores["search_hits"], scores["search_misses"]) == (1.0, 2, [])
    assert "pairs" not in scores and "matches" not in scores  # the review rows are in matches.json
    matches = json.loads((folder / "matches.json").read_text(encoding="utf-8"))
    assert [row["gold_id"] for row in matches] == ["pep9999-r1", "pep9999-r2", "pep9999-r3"]
    assert [row["matched"] for row in matches] == [True, True, False]
    assert set(matches[0]) == {
        "gold_id", "idea", "recoverable", "matched", "option_key", "title", "status", "status_kind", "score"
    }
    assert store.record_for_thread("pep:9999") is not None

    assert summary["peps"][0]["pep"] == 9999
    assert "pairs" not in summary["peps"][0] and "matches" not in summary["peps"][0]
    assert (summary["model"], summary["mode"]) == ("scripted", "scripted")
    assert not (out_dir / "summary.md").exists() and not (out_dir / "summary.json").exists()
    assert json.loads((out_dir / "eval-summary.json").read_text(encoding="utf-8"))["peps"][0]["pep"] == 9999
    text = (out_dir / "eval-summary.md").read_text(encoding="utf-8")
    assert "with `scripted`" in text
    assert "Not a live model run" in text
    table = text.splitlines()
    assert any(line.startswith("| 9999 |") and "| 2 (2 / 0) |" in line for line in table)
    assert any(line.startswith("| 9999 |") and line.endswith("| 1.000 |") for line in table)  # search@5
    assert "| Closed-book recall | search@5 |" in text
    assert any(line.startswith("| **Macro average** |") for line in table)
    assert messages


# Search recall at 5 -------------------------------------------------------------------


def search_record(record_id: str, options: list[tuple[str, str, str]]) -> DecisionRecord:
    """A record whose options are (key, title, reason) triples; nothing else matters to search."""
    return DecisionRecord(
        id=record_id,
        thread_id=f"pep:{record_id}",
        question="q",
        outcome="o",
        options=[
            Option(key=key, title=title, reasons=[Reason(stance="con", text=reason)] if reason else [])
            for key, title, reason in options
        ],
    )


def tiny_corpus() -> list[DecisionRecord]:
    return [
        search_record(
            "dr-aaaa0001",
            [
                ("A1", "Decorator-based opt-in for lazy widgets", "Decorators cannot reach import statements."),
                ("A2", "Immutable widget objects", "Values never change once built."),
            ],
        ),
        search_record("dr-bbbb0002", [("A1", "Soft keyword for lazy names", "Old code keeps working.")]),
    ]


def test_search_recall_keyword_hit_and_paraphrase_miss():
    hit = GoldItem(id="g1", idea="Using a `decorator` instead of a keyword")  # shares "decorator"
    miss = GoldItem(id="g2", idea="Freeze instances after creation")  # a paraphrase: no shared word
    entries = [
        (hit, "dr-aaaa0001:A1", "Decorator-based opt-in for lazy widgets"),
        (miss, "dr-aaaa0001:A2", "Immutable widget objects"),
    ]
    index = OptionIndex(tiny_corpus())
    try:
        expected = {
            "search_recall_at_5": 0.5,
            "search_hits": 1,
            "search_misses": [
                {
                    "gold_id": "g2",
                    "idea": "Freeze instances after creation",
                    "matched_option_title": "Immutable widget objects",
                    "rank_or_null": None,
                }
            ],
        }
        assert search_recall(entries, index) == expected
        # Without FTS5 the token-overlap fallback gives the same answer here.
        index.fts = False
        assert search_recall(entries, index) == expected
    finally:
        index.close()


def test_search_recall_counts_only_the_top_5():
    fillers = [(f"A{n}", "keyword keyword keyword", "") for n in range(1, 7)]
    unrelated = [(f"A{n}", f"Unrelated option number {n}", "") for n in range(1, 9)]
    target = ("A1", "Soft keyword syntax for lazy imports", "Old code keeps working with the new syntax.")
    corpus = [
        search_record("dr-aaaa0001", fillers),
        search_record("dr-bbbb0002", [target]),
        search_record("dr-cccc0003", unrelated),
    ]
    entries = [(GoldItem(id="g1", idea="Keyword"), "dr-bbbb0002:A1", target[1])]
    index = OptionIndex(corpus)
    try:
        assert index.ranking("Keyword")[:6] == [f"dr-aaaa0001:A{n}" for n in range(1, 7)]
        result = search_recall(entries, index)
        assert SEARCH_K == 5
        assert (result["search_recall_at_5"], result["search_hits"]) == (0.0, 0)
        assert result["search_misses"][0]["rank_or_null"] == 7  # found, but below the top 5
    finally:
        index.close()


def test_search_query_syntax_cannot_break_fts():
    index = OptionIndex(tiny_corpus())
    try:
        assert index.ranking('Use "NEAR" OR `AND` (x) - y*: NOT z') == []
        assert index.ranking("") == []
        assert index.ranking("DECORATOR!!")[0] == "dr-aaaa0001:A1"
    finally:
        index.close()


def test_search_recall_with_nothing_matched_is_undefined():
    index = OptionIndex(tiny_corpus())
    try:
        assert search_recall([], index) == {"search_recall_at_5": None, "search_hits": 0, "search_misses": []}
    finally:
        index.close()


def test_matched_entries_follow_the_gold_matching(sample_record):
    gold = make_gold()
    scores = score_record(gold, sample_record)
    entries = matched_entries(gold, sample_record, scores["matches"])
    assert [(item.id, row_id) for item, row_id, _ in entries] == [
        ("pep9999-r1", f"{sample_record.id}:A1"),
        ("pep9999-r2", f"{sample_record.id}:A2"),
    ]  # pep9999-r3 was never matched, so it is not a search query
    text = option_search_text(sample_record.options[0])
    assert text.startswith("Use a decorator instead of a new keyword")
    assert "We rejected the decorator approach" in text  # quotes are searchable too
    index = OptionIndex([sample_record])
    try:
        assert search_recall(entries, index)["search_recall_at_5"] == 1.0
    finally:
        index.close()
