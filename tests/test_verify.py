"""Tests for decrack.verify: evidence checks on one record, and on example folders and live runs."""

from __future__ import annotations

import json
from pathlib import Path

from decrack.models import DecisionRecord, Thread
from decrack.text import finalize_post
from decrack.verify import check_record, main, verify_examples

# Citations in the sample record: 10 option evidence, 6 reason evidence and 10 status-history evidence.
QUOTES_PER_RECORD = 26


def dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def write_example(folder: Path, thread: Thread, records: list[DecisionRecord], mode: str | None = None) -> None:
    """An example folder as `decrack run --out` writes it; with ``mode``, a run.json for a run of that mode too."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "thread.json").write_text(dump(thread.model_dump(mode="json")), encoding="utf-8")
    (folder / "records.json").write_text(dump([r.model_dump(mode="json") for r in records]), encoding="utf-8")
    if mode is not None:
        run = records[0].run.model_copy(update={"mode": mode})
        (folder / "run.json").write_text(dump(run.model_dump(mode="json")), encoding="utf-8")


# check_record ---------------------------------------------------------------------


def test_sample_record_passes(synthetic_thread, sample_record):
    assert check_record(synthetic_thread, sample_record) == []


def test_edited_post_is_source_changed(synthetic_thread, sample_record):
    post = synthetic_thread.posts[4]  # alice's post 5, cited by A1 and A2
    post.text = post.text.replace("rejected", "turned down")
    finalize_post(post)
    post.version = 2

    rid = sample_record.id
    message = "source_changed: the thread has version 2 of the post, the evidence cites version 1"
    assert check_record(synthetic_thread, sample_record) == [
        f"{rid} A1 evidence {post.id} s2: {message}",
        f"{rid} A1 reason 1 {post.id} s2: {message}",
        f"{rid} A1 event 2 {post.id} s2: {message}",
        f"{rid} A2 evidence {post.id} s3: {message}",
        f"{rid} A2 reason 1 {post.id} s3: {message}",
        f"{rid} A2 event 2 {post.id} s3: {message}",
    ]


def test_changed_text_is_source_changed_at_the_same_version(synthetic_thread, sample_record):
    post = synthetic_thread.posts[4]
    post.text = post.text.replace("rejected", "turned down")  # the stored hash is now stale
    stale = check_record(synthetic_thread, sample_record)
    finalize_post(post)  # re-hashed but still version 1, as when a GitHub comment is edited
    rehashed = check_record(synthetic_thread, sample_record)

    message = "source_changed: the post text no longer has the sha256 the evidence cites"
    for problems in (stale, rehashed):
        assert len(problems) == 6
        assert all(f" {post.id} " in problem and problem.endswith(message) for problem in problems)


def test_deleted_post_is_not_found(synthetic_thread, sample_record):
    removed = synthetic_thread.posts.pop(5)  # erin's objection to the global flag (A2)
    rid = sample_record.id
    message = "not_found: the post is not in the thread"
    assert check_record(synthetic_thread, sample_record) == [
        f"{rid} A2 evidence {removed.id} s1: {message}",
        f"{rid} A2 reason 2 {removed.id} s1: {message}",
        f"{rid} A2 event 3 {removed.id} s1: {message}",
    ]


def test_wrong_offsets(synthetic_thread, sample_record):
    ev = sample_record.options[0].evidence[0]  # A1 cites p2.s1, which is text[0:49]
    ev.start = 1
    prefix = f"{sample_record.id} A1 evidence dpo:99999:1002 s1: "
    assert check_record(synthetic_thread, sample_record) == [
        prefix + "start/end 1:49 do not match the cited sentences, which span 0:49",
        prefix + "quote differs from the post text at 1:49",
    ]


def test_wrong_quote(synthetic_thread, sample_record):
    sample_record.options[0].evidence[0].quote = "Why not use a macro instead of a new keyword?"
    assert check_record(synthetic_thread, sample_record) == [
        f"{sample_record.id} A1 evidence dpo:99999:1002 s1: quote differs from the post text at 0:49"
    ]


def test_non_contiguous_run(synthetic_thread, sample_record):
    sample_record.options[1].evidence[1].sentence_indexes = [1, 3]  # A2 cites post 5
    assert check_record(synthetic_thread, sample_record) == [
        f"{sample_record.id} A2 evidence dpo:99999:1005 s1,3: sentence indexes [1, 3] are not one contiguous run"
    ]


def test_out_of_range_sentence(synthetic_thread, sample_record):
    sample_record.options[2].evidence[0].sentence_indexes = [3]  # post 7 has two sentences
    assert check_record(synthetic_thread, sample_record) == [
        f"{sample_record.id} A3 evidence dpo:99999:1007 s3:"
        " sentence indexes [3] are out of range (the post has 2 sentences)"
    ]


def test_option_without_evidence(synthetic_thread, sample_record):
    sample_record.options[1].evidence = []
    assert check_record(synthetic_thread, sample_record) == [f"{sample_record.id} A2: option has no evidence"]


def test_source_check_must_be_valid(synthetic_thread, sample_record):
    sample_record.options[3].reasons[0].evidence[1].source_check = "source_changed"
    assert check_record(synthetic_thread, sample_record) == [
        f"{sample_record.id} A4 reason 1 dpo:99999:1008 s2: source_check is 'source_changed', not 'valid'"
    ]


def test_record_for_another_thread(synthetic_thread, sample_record):
    other = synthetic_thread.model_copy(update={"id": "pep:1"})
    problems = check_record(other, sample_record)
    assert len(problems) == 1
    assert sample_record.id in problems[0]
    assert "pep:1" in problems[0]


# verify_examples ------------------------------------------------------------------


def test_verify_examples_walks_nested_dirs(tmp_path, synthetic_thread, sample_record):
    write_example(tmp_path / "a", synthetic_thread, [sample_record])
    write_example(tmp_path / "nested" / "pep-9999", synthetic_thread, [sample_record])
    (tmp_path / "nested" / "summary.md").write_text("# Summary\n", encoding="utf-8")
    (tmp_path / "okf").mkdir()
    # Outside examples/runs, no run.json is needed.
    assert verify_examples(tmp_path) == (2, [])


def test_verify_examples_includes_the_root(tmp_path, synthetic_thread, sample_record):
    write_example(tmp_path, synthetic_thread, [sample_record])
    assert verify_examples(tmp_path) == (1, [])


def test_runs_must_be_live(tmp_path, synthetic_thread, sample_record):
    root = tmp_path / "examples"
    run_dir = root / "runs" / "x"
    label = run_dir.as_posix()
    for mode in ("replay", "scripted"):
        write_example(run_dir, synthetic_thread, [sample_record], mode=mode)
        count, problems = verify_examples(root)
        assert count == 1
        assert len(problems) == 1
        assert problems[0].startswith(f"{label}: refused: run.json has mode '{mode}', not 'live'")
        # The rule holds whichever folder the check starts from.
        assert verify_examples(run_dir) == (count, problems)

    write_example(run_dir, synthetic_thread, [sample_record], mode="live")
    assert verify_examples(root) == (1, [])
    assert verify_examples(run_dir) == (1, [])
    assert verify_examples(tmp_path) == (1, [])


def test_runs_need_a_run_json(tmp_path, synthetic_thread, sample_record):
    root = tmp_path / "examples"
    run_dir = root / "runs" / "pep-9999"
    write_example(run_dir, synthetic_thread, [sample_record])
    missing = "run.json is missing; examples/runs holds only live model runs, each with its run.json"
    assert verify_examples(root) == (1, [f"{run_dir.as_posix()}: {missing}"])

    (run_dir / "run.json").write_text("not json\n", encoding="utf-8")
    count, problems = verify_examples(root)
    assert count == 1
    assert len(problems) == 1
    assert problems[0].startswith(f"{run_dir.as_posix()}: cannot read run.json: ")


def test_verify_examples_reports_problems(tmp_path, synthetic_thread, sample_record):
    sample_record.options[0].evidence[0].quote = "Tampered."
    write_example(tmp_path / "bad", synthetic_thread, [sample_record])
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    (lonely / "records.json").write_text("[]\n", encoding="utf-8")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "thread.json").write_text(dump(synthetic_thread.model_dump(mode="json")), encoding="utf-8")
    (broken / "records.json").write_text(dump({"not": "a list"}), encoding="utf-8")

    count, problems = verify_examples(tmp_path)
    assert count == 2
    bad = (tmp_path / "bad").as_posix()
    assert f"{bad}: {sample_record.id} A1 evidence dpo:99999:1002 s1: quote differs from the post text at 0:49" in (
        problems
    )
    assert any("lonely" in p and "thread.json" in p for p in problems)
    assert any("broken" in p and "JSON list" in p for p in problems)
    assert len(problems) == 3


def test_verify_examples_on_a_missing_or_empty_dir(tmp_path):
    assert verify_examples(tmp_path / "missing") == (0, [])
    assert verify_examples(tmp_path) == (0, [])


# main -----------------------------------------------------------------------------


def test_main_without_examples(tmp_path, capsys):
    assert main(tmp_path / "missing") == 0
    assert "nothing to verify" in capsys.readouterr().out
    assert main(tmp_path) == 0
    assert "No examples yet" in capsys.readouterr().out


def test_main_reports_ok_then_failure(tmp_path, capsys, synthetic_thread, sample_record):
    write_example(tmp_path / "good", synthetic_thread, [sample_record])
    assert main(tmp_path) == 0
    assert capsys.readouterr().out.strip().endswith(
        f"verified 1 example(s), {QUOTES_PER_RECORD} quote(s) checked: OK"
    )

    bad = sample_record.model_copy(deep=True)
    bad.options[0].evidence[0].quote = "Tampered."
    write_example(tmp_path / "bad", synthetic_thread, [bad])
    assert main(tmp_path) == 1
    out = capsys.readouterr().out
    assert f"{bad.id} A1 evidence dpo:99999:1002 s1: quote differs from the post text at 0:49" in out
    assert out.strip().endswith(f"verified 2 example(s), {2 * QUOTES_PER_RECORD} quote(s) checked: 1 problem(s)")
