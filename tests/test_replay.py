"""Recompile every committed real-run example from recorded model answers and compare with its stored record.

Needs ``tests/fixtures/llm_calls.jsonl`` (written by ``decrack export calls``)
and ``examples/**/records.json`` next to a ``thread.json``, as in
``examples/runs/<name>/``. Skips otherwise. Replay proves the pipeline logic,
not the model: the answers are the ones the real model gave.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decrack.config import DEFAULT_MODEL, Settings
from decrack.models import DecisionRecord, Thread
from decrack.pipeline.llm import ReplayLLM, ReplayMissError
from decrack.pipeline.run import compile_thread

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "llm_calls.jsonl"
EXAMPLES = ROOT / "examples"
# RunInfo.params entries that are also Settings fields: they decide the windows and the steps that run.
REPLAYED_PARAMS = ("num_ctx", "window_max_tokens", "window_overlap_tokens", "support_check")


def example_dirs() -> list[Path]:
    if not EXAMPLES.is_dir():
        return []
    return sorted(path.parent for path in EXAMPLES.rglob("records.json") if (path.parent / "thread.json").is_file())


def replay_settings(record: DecisionRecord) -> Settings:
    """Default settings with the window sizes, num_ctx and support switch of the recorded run."""
    params = record.run.params if record.run else {}
    return Settings(**{name: params[name] for name in REPLAYED_PARAMS if name in params})


def outline(record: DecisionRecord) -> list[tuple[str, str, str, str]]:
    return [(option.key, option.title, option.status, option.status_kind) for option in record.options]


@pytest.mark.parametrize(
    "example",
    example_dirs() or [None],
    ids=lambda example: example.relative_to(ROOT).as_posix() if example else "no-examples",
)
def test_examples_replay(example: Path | None):
    if not FIXTURE.is_file():
        pytest.skip("tests/fixtures/llm_calls.jsonl is missing; record it with `decrack export calls --out <path>`")
    if example is None:
        pytest.skip("no examples/**/records.json with a sibling thread.json")

    thread = Thread.model_validate_json((example / "thread.json").read_text(encoding="utf-8"))
    rows = json.loads((example / "records.json").read_text(encoding="utf-8"))
    records = [DecisionRecord.model_validate(row) for row in rows]
    stored = next((record for record in records if record.thread_id == thread.id), None)
    if stored is None:
        pytest.skip(f"{example.name}: records.json has no record for {thread.id}")

    settings = replay_settings(stored)
    llm = ReplayLLM(FIXTURE, model=stored.run.model if stored.run else DEFAULT_MODEL, num_ctx=settings.num_ctx)
    try:
        rebuilt = compile_thread(thread, llm, settings)
    except ReplayMissError as exc:
        pytest.skip(f"{example.name}: the fixture lacks a recorded call: {exc}")

    assert outline(rebuilt) == outline(stored)
    assert rebuilt.run.mode == "replay"
