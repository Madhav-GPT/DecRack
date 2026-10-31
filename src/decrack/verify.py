"""Re-check every citation of saved runs against their threads (``decrack verify``).

An example directory holds ``thread.json`` (a Thread) and ``records.json`` (a
JSON list of DecisionRecord), as written by ``decrack run --out`` and
``decrack eval``. An Evidence is valid only when:

- its post, found by its stable id, is in the thread (else ``not_found``);
- the post is the cited version, and the post's stored hash, the cited hash and
  the hash of the post's text all agree (else ``source_changed``);
- its sentence indexes are one contiguous run inside the post;
- ``start`` and ``end`` are the span of those sentences;
- its quote is exactly ``text[start:end]``;
- its ``source_check`` is ``valid``.

Every option must have evidence. ``examples/runs/`` holds real model runs
only: each directory there must also hold ``run.json`` with ``mode`` set to
``live``. Replayed or scripted output proves the pipeline logic, not the
model, so it is refused there. Example directories elsewhere (in tests, say)
need no ``run.json``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from decrack.models import DecisionRecord, Evidence, Option, Thread
from decrack.text import sha256_text

RUNS_DIR = ("examples", "runs")


def _label(ev: Evidence) -> str:
    """``dpo:99999:1005 s2`` or ``dpo:99999:1003 s1,2``: the cited post id and sentence indexes."""
    indexes = ",".join(str(index) for index in ev.sentence_indexes) or "?"
    return f"{ev.post_id} s{indexes}"


def _check_evidence(thread: Thread, ev: Evidence) -> list[str]:
    """Problems with one Evidence, as short messages; an empty list means it is valid.

    A missing post gives one ``not_found:`` message and a changed post one
    ``source_changed:`` message; the offset checks only run against the cited text.
    """
    post = thread.post_by_id(ev.post_id)
    if post is None:
        return ["not_found: the post is not in the thread"]
    if post.version != ev.post_version:
        return [
            f"source_changed: the thread has version {post.version} of the post,"
            f" the evidence cites version {ev.post_version}"
        ]
    if not post.sha256 == ev.post_sha256 == sha256_text(post.text):
        return ["source_changed: the post text no longer has the sha256 the evidence cites"]
    indexes = sorted(ev.sentence_indexes)
    if not indexes:
        return ["no sentence indexes"]
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        return [f"sentence indexes {ev.sentence_indexes} are not one contiguous run"]
    if indexes[0] < 1 or indexes[-1] > len(post.spans):
        return [f"sentence indexes {ev.sentence_indexes} are out of range (the post has {len(post.spans)} sentences)"]
    problems: list[str] = []
    start, end = post.spans[indexes[0] - 1].start, post.spans[indexes[-1] - 1].end
    if (ev.start, ev.end) != (start, end):
        problems.append(f"start/end {ev.start}:{ev.end} do not match the cited sentences, which span {start}:{end}")
    if post.text[ev.start : ev.end] != ev.quote:
        problems.append(f"quote differs from the post text at {ev.start}:{ev.end}")
    if ev.source_check != "valid":
        problems.append(f"source_check is {ev.source_check!r}, not 'valid'")
    return problems


def _citations(option: Option) -> list[tuple[str, Evidence]]:
    """Every Evidence of an option with where it sits: ``evidence``, ``reason N`` or ``event N`` of its history."""
    cited = [("evidence", ev) for ev in option.evidence]
    for number, reason in enumerate(option.reasons, start=1):
        cited.extend((f"reason {number}", ev) for ev in reason.evidence)
    for number, event in enumerate(option.status_history, start=1):
        cited.extend((f"event {number}", ev) for ev in event.evidence)
    return cited


def check_record(thread: Thread, record: DecisionRecord) -> list[str]:
    """Problems with ``record`` against ``thread``; an empty list means every citation is valid.

    Each problem names the record id, the option key, where the citation sits
    and the cited post id with its sentence indexes, then what is wrong.
    """
    if record.thread_id != thread.id:
        return [f"{record.id}: record is for thread {record.thread_id}, but the thread is {thread.id}"]
    problems: list[str] = []
    for option in record.options:
        if not option.evidence:
            problems.append(f"{record.id} {option.key}: option has no evidence")
        for where, ev in _citations(option):
            prefix = f"{record.id} {option.key} {where} {_label(ev)}"
            problems.extend(f"{prefix}: {message}" for message in _check_evidence(thread, ev))
    return problems


def _evidence_count(record: DecisionRecord) -> int:
    return sum(len(_citations(option)) for option in record.options)


def _in_runs(folder: Path) -> bool:
    """True for ``examples/runs`` and every directory below it, where only live runs belong."""
    parts = folder.resolve().parts
    return any(parts[index : index + 2] == RUNS_DIR for index in range(len(parts) - 1))


def _check_run_file(folder: Path) -> list[str]:
    """Problems with the ``run.json`` of a directory under examples/runs; empty for a live run."""
    path = folder / "run.json"
    if not path.is_file():
        return ["run.json is missing; examples/runs holds only live model runs, each with its run.json"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read run.json: {exc}"]
    mode = data.get("mode") if isinstance(data, dict) else None
    if mode != "live":
        return [
            f"refused: run.json has mode {mode!r}, not 'live'; examples/runs holds only live model runs"
            " (replay and scripted runs prove the pipeline logic, not the model)"
        ]
    return []


def _verify(root: Path) -> tuple[int, int, list[str]]:
    """(example dirs checked, citations checked, problems) for every example dir under ``root``."""
    examples = quotes = 0
    problems: list[str] = []
    if not root.is_dir():
        return examples, quotes, problems
    for records_path in sorted(root.rglob("records.json")):
        folder = records_path.parent
        label = folder.as_posix()
        thread_path = folder / "thread.json"
        if not thread_path.is_file():
            problems.append(f"{label}: records.json has no thread.json next to it")
            continue
        examples += 1
        if _in_runs(folder):
            problems.extend(f"{label}: {problem}" for problem in _check_run_file(folder))
        try:
            thread = Thread.model_validate_json(thread_path.read_text(encoding="utf-8"))
            data = json.loads(records_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("records.json must hold a JSON list of decision records")
            records = [DecisionRecord.model_validate(item) for item in data]
        except (OSError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
            problems.append(f"{label}: cannot read the example: {exc}")
            continue
        for record in records:
            quotes += _evidence_count(record)
            problems.extend(f"{label}: {problem}" for problem in check_record(thread, record))
    return examples, quotes, problems


def verify_examples(root: str | Path) -> tuple[int, list[str]]:
    """Check every dir under ``root`` (root included) that holds thread.json and records.json.

    Returns the number of example dirs checked and the problems found.
    """
    examples, _, problems = _verify(Path(root))
    return examples, problems


def main(root: str | Path = "examples") -> int:
    """Print one line per problem and a summary; return 1 if any check failed, else 0."""
    root = Path(root)
    examples, quotes, problems = _verify(root)
    if examples == 0 and not problems:
        print(f"No examples yet under {root}; nothing to verify.")
        return 0
    for problem in problems:
        print(problem)
    summary = f"verified {examples} example(s), {quotes} quote(s) checked"
    if problems:
        print(f"{summary}: {len(problems)} problem(s)")
        return 1
    print(f"{summary}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "examples"))
