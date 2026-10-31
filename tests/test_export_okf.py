"""Tests for decrack.export_okf: one OKF record file and the whole bundle."""

from __future__ import annotations

import re

import pytest

from decrack.export_okf import OKF_SPEC_COMMIT, OKF_VERSION, export_bundle, record_filename, render_record

THREAD_URL = "https://discuss.python.org/t/pep-9999-lazy-widgets/99999"
FOOTNOTE_USE = re.compile(r"\[\^([^\]\s]+)\](?!:)")
FOOTNOTE_DEF = re.compile(r"^\[\^([^\]\s]+)\]:", re.MULTILINE)
SLUG = re.compile(r"^[a-z0-9-]+$")


def split_front(text: str) -> tuple[str, str]:
    """(frontmatter without the --- lines, body)."""
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return text[4:end], text[end + len("\n---\n") :]


def section(body: str, heading: str) -> str:
    """The text under a level-1 heading, up to the next level-1 heading."""
    return body.split(f"\n{heading}\n", 1)[1].split("\n# ", 1)[0]


def assert_footnotes_resolve(front: str, body: str) -> None:
    uses = FOOTNOTE_USE.findall(body)
    defs = FOOTNOTE_DEF.findall(body)
    assert uses
    assert len(defs) == len(set(defs)), "a footnote is defined twice"
    assert set(uses) == set(defs), "every used footnote is defined, and every definition is used"
    for label in defs:
        assert SLUG.match(label), f"footnote label {label!r} is not a plain slug"
        assert f'id: "{label}"' in front


def test_render_record_frontmatter(sample_record, synthetic_thread):
    text = render_record(sample_record, synthetic_thread)
    assert text.startswith("---\n")
    front, _ = split_front(text)
    assert front.startswith('type: "Decision Record"\n')
    assert 'title: "PEP 9999: Lazy widgets"' in front
    assert f'resource: "{THREAD_URL}"' in front
    assert 'status: "stable"' in front
    assert 'by: "decrack/0.1.0"' in front
    assert 'at: "2026-11-01T01:00:00Z"' in front
    assert 'by: "process:decrack-quote-check"' in front
    assert "stale_after" not in front  # no age decay
    assert '  - id: "dpo-99999-1005"' in front
    assert 'title: "Post #5 by alice"' in front
    assert 'author: "human:alice@discuss.python.org"' in front
    assert 'last_modified: "2026-01-05T10:00:00Z"' in front
    assert "\ndecrack:\n" in front
    assert '  schema: "decrack-record/0.2"' in front
    assert '  thread_id: "pep:9999"' in front
    assert '  decided_in_post: "dpo:99999:1008"' in front
    assert f'digest: "sha256:{synthetic_thread.posts[4].sha256}"' in front
    assert 'status_kind: "confirmed"' in front
    assert 'status_basis: "author_statement"' in front
    assert 'source_check: "valid"' in front
    assert 'support: "supported"' in front
    assert 'evidence_type: "decision_statement"' in front
    assert "commit: null" in front


def test_render_record_body(sample_record, synthetic_thread):
    front, body = split_front(render_record(sample_record, synthetic_thread))
    headings = [line for line in body.splitlines() if line.startswith("# ")]
    assert headings == [
        "# Question",
        "# Decision outcome",
        "# Considered options",
        "# Rejected ideas",
        "# Code",
        "# Evidence",
    ]
    outcome = section(body, "# Decision outcome")
    assert "4 options: 1 accepted, 3 rejected. Decided in post #8 by sam (decider).[^dpo-99999-1008]" in outcome

    rows = [line for line in section(body, "# Considered options").splitlines() if line.startswith("|")]
    assert rows[0] == "| Option | Status | Kind | Confidence | Main reason |"
    assert len(rows) == 2 + len(sample_record.options)
    for option in sample_record.options:
        assert sum(f"| {option.title} ({option.key}) |" in row for row in rows) == 1
    assert (
        "| Use a decorator instead of a new keyword (A1) | rejected | confirmed | high"
        " | Decorators cannot apply to import statements. |"
    ) in rows

    rejected = section(body, "# Rejected ideas")
    assert "## Use a decorator instead of a new keyword" in rejected
    assert "## Global flag to enable laziness everywhere" in rejected
    assert "## Hard lazy keyword" in rejected
    assert "## Soft keyword" not in rejected
    assert (
        "Status: rejected (confirmed, confidence high)."
        " Basis: author statement by alice (author) in post #5.[^dpo-99999-1005]"
    ) in rejected
    assert (
        "Status: rejected (confirmed, confidence high)."
        " Basis: decider statement by sam (decider) in post #8.[^dpo-99999-1008]"
    ) in rejected
    assert "- con: Decorators cannot apply to import statements.[^dpo-99999-1005]" in rejected

    code = section(body, "# Code")
    assert "- `Lib/widgets.py` (example/widgets): mentioned, direct" in code
    assert "- `Lib/lazy.py` (example/widgets, PR #42): pr_files, historical" in code

    evidence = section(body, "# Evidence")
    assert (
        f"- > Why not use a decorator instead of a new keyword? ([dpo:99999:1002 s1]({THREAD_URL}/2))[^dpo-99999-1002]"
    ) in evidence
    assert f"([dpo:99999:1003 s1-s2]({THREAD_URL}/3))[^dpo-99999-1003]" in evidence
    assert f"[^dpo-99999-1001]: Post #1 by alice, {THREAD_URL}/1" in evidence
    assert_footnotes_resolve(front, body)


def test_status_note_and_kind_are_shown(sample_record):
    option = sample_record.options[1]
    option.status_kind = "inferred"
    option.confidence = "medium"
    option.status_note = "inferred from objections by 2 participants (weaker)"
    _, body = split_front(render_record(sample_record))
    rejected = section(body, "# Rejected ideas")
    assert "Status: rejected (inferred, confidence medium)." in rejected
    assert "inferred from objections by 2 participants (weaker)." in rejected
    rows = section(body, "# Considered options")
    assert "| Global flag to enable laziness everywhere (A2) | rejected | inferred | medium |" in rows


def test_render_record_without_thread(sample_record, synthetic_thread):
    text = render_record(sample_record)
    front, body = split_front(text)
    assert "last_modified" not in front
    # Digests, authors and URLs come from the evidence itself.
    assert f'digest: "sha256:{synthetic_thread.posts[4].sha256}"' in front
    assert 'title: "Post dpo:99999:1005 by alice"' in front
    assert 'author: "human:alice@discuss.python.org"' in front
    assert f"[^dpo-99999-1005]: Post dpo:99999:1005 by alice, {THREAD_URL}/5" in body
    assert "Decided in post dpo:99999:1008 by sam (decider).[^dpo-99999-1008]" in body
    assert_footnotes_resolve(front, body)
    # A thread for another id is ignored rather than mixed in.
    other = synthetic_thread.model_copy(update={"id": "pep:1"})
    assert render_record(sample_record, other) == text


def test_footnote_ids_are_unique_slugs(sample_record):
    """Post ids hold ':', '/' and '#'; footnote and source ids keep only [a-z0-9-] and never collide."""
    record = sample_record.model_copy(deep=True)
    new_ids = ["gh:o/r#12:c34", "gh:o/r#12-c34", "file:1a2b3c4d:3"]  # the first two slug the same way
    cited = record.options[0].evidence + record.options[1].evidence
    for ev, post_id in zip(cited, new_ids):
        ev.post_id = post_id
    front, body = split_front(render_record(record))
    labels = FOOTNOTE_DEF.findall(body)
    assert {"gh-o-r-12-c34", "gh-o-r-12-c34-2", "file-1a2b3c4d-3"} <= set(labels)
    assert_footnotes_resolve(front, body)


def test_unverified_record_is_a_draft(sample_record):
    draft = sample_record.model_copy(update={"verification": "unverified"})
    front, _ = split_front(render_record(draft))
    assert 'status: "draft"' in front
    assert "verified:" not in front


def test_record_filename(sample_record):
    name = record_filename(sample_record)
    assert re.fullmatch(r"dr-[0-9a-f]{8}-[a-z0-9-]+\.md", name)
    assert name.startswith(f"{sample_record.id}-")


def test_export_bundle(tmp_path, sample_record, synthetic_thread):
    out = tmp_path / "okf"
    stale = out / "decisions" / "dr-deadbeef-old-record.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old\n", encoding="utf-8")
    notes = out / "decisions" / "notes.md"
    notes.write_text("kept\n", encoding="utf-8")

    written = export_bundle([sample_record], out, threads={synthetic_thread.id: synthetic_thread})

    name = record_filename(sample_record)
    record_file = out / "decisions" / name
    assert set(written) == {record_file, out / "decisions" / "index.md", out / "log.md", out / "index.md"}
    assert record_file.read_text(encoding="utf-8") == render_record(sample_record, synthetic_thread)
    assert not stale.exists()
    assert notes.exists()

    index = (out / "index.md").read_text(encoding="utf-8")
    assert index.startswith(f'---\nokf_version: "{OKF_VERSION}"\n---\n')
    assert "# Projects" in index
    assert "* [Decisions](decisions/index.md) - " in index
    assert f"spec commit {OKF_SPEC_COMMIT}" in index

    decisions_index = (out / "decisions" / "index.md").read_text(encoding="utf-8")
    assert not decisions_index.startswith("---")
    assert f"* [PEP 9999: Lazy widgets]({name}) - 4 options: 1 accepted, 3 rejected." in decisions_index

    log = (out / "log.md").read_text(encoding="utf-8")
    assert not log.startswith("---")
    assert log.startswith("## 2026-11-01\n")
    assert (
        f"* **Verification**: quote check passed for [{sample_record.id}](decisions/{name}), 13 of 13 quotes valid."
    ) in log
    assert f"* **Creation**: extracted {sample_record.id} from {THREAD_URL}." in log

    for path in out.rglob("*.md"):
        assert "](/" not in path.read_text(encoding="utf-8"), f"absolute link in {path}"


def test_log_passes_the_quote_check_only_when_every_quote_is_valid(tmp_path, sample_record):
    export_bundle([sample_record], tmp_path / "valid")
    assert "quote check passed" in (tmp_path / "valid" / "log.md").read_text(encoding="utf-8")

    sample_record.options[0].evidence[0].source_check = "source_changed"
    export_bundle([sample_record], tmp_path / "changed")
    log = (tmp_path / "changed" / "log.md").read_text(encoding="utf-8")
    assert "quote check passed" not in log
    assert f"* **Creation**: extracted {sample_record.id} from {THREAD_URL}." in log


def test_export_bundle_is_byte_identical(tmp_path, sample_record, synthetic_thread):
    out = tmp_path / "okf"
    threads = {synthetic_thread.id: synthetic_thread}

    def snapshot() -> dict:
        return {path.relative_to(out).as_posix(): path.read_bytes() for path in out.rglob("*") if path.is_file()}

    export_bundle([sample_record], out, threads=threads)
    first = snapshot()
    export_bundle([sample_record], out, threads=threads)
    assert snapshot() == first
    assert len(first) == 4


def test_export_bundle_removes_records_no_longer_exported(tmp_path, sample_record):
    other = sample_record.model_copy(
        update={"id": "dr-0000beef", "thread_id": "pep:1234", "question": "Another lazy question"}
    )
    out = tmp_path / "okf"
    export_bundle([sample_record, other], out)
    assert (out / "decisions" / record_filename(other)).is_file()
    assert record_filename(other) in (out / "decisions" / "index.md").read_text(encoding="utf-8")

    export_bundle([sample_record], out)
    assert not (out / "decisions" / record_filename(other)).exists()
    assert (out / "decisions" / record_filename(sample_record)).is_file()
    assert record_filename(other) not in (out / "decisions" / "index.md").read_text(encoding="utf-8")


def test_frontmatter_parses_as_yaml(sample_record, synthetic_thread):
    yaml = pytest.importorskip("yaml")
    front, body = split_front(render_record(sample_record, synthetic_thread))
    data = yaml.safe_load(front)
    assert data["type"] == "Decision Record"
    assert data["status"] == "stable"
    assert data["tags"] == ["decrack", "pep-9999", "accepted", "rejected"]
    assert data["generated"] == {"by": "decrack/0.1.0", "at": "2026-11-01T01:00:00Z"}
    assert data["verified"] == [{"by": "process:decrack-quote-check", "at": "2026-11-01T01:00:00Z"}]
    assert "stale_after" not in data

    decrack = data["decrack"]
    assert decrack["schema"] == "decrack-record/0.2"
    assert decrack["decided_in_post"] == "dpo:99999:1008"
    assert decrack["decided_by"] == {"handle": "sam", "role": "decider"}
    assert (decrack["run_mode"], decrack["support_checked"]) == ("scripted", True)
    assert [option["key"] for option in decrack["options"]] == ["A1", "A2", "A3", "A4"]
    first = decrack["options"][0]
    assert first["status"] == "rejected"
    assert first["status_kind"] == "confirmed"
    assert first["status_basis"] == "author_statement"
    assert first["status_post"] == "dpo:99999:1005"
    assert first["decided_by"] == {"handle": "alice", "role": "author"}
    assert first["status_note"] == ""
    assert first["confidence"] == "high"
    assert first["evidence"] == ["ev-1", "ev-2"]
    assert first["reasons"][0]["evidence"] == ["ev-2"]
    assert first["reasons"][0]["support"] == "supported"
    assert [event["act"] for event in first["history"]] == ["propose", "reject"]
    assert [event["evidence"] for event in first["history"]] == [["ev-1"], ["ev-2"]]
    assert first["history"][1]["role"] == "author"

    # 12 distinct quotes in options and reasons, plus carol's first sentence cited only by A4's history.
    assert len(decrack["evidence"]) == 13
    post = synthetic_thread.posts[1]
    ev = decrack["evidence"][0]
    assert ev["post_id"] == post.id
    assert ev["post_version"] == 1
    assert ev["digest"] == f"sha256:{post.sha256}"
    assert ev["sentence_indexes"] == [1]
    assert (ev["start"], ev["end"]) == (0, len(post.sentences[0]))
    assert ev["quote"] == post.sentences[0] == "Why not use a decorator instead of a new keyword?"
    assert ev["url"] == post.url
    assert (ev["source_check"], ev["support"], ev["evidence_type"]) == ("valid", "supported", "proposal")
    run = next(item for item in decrack["evidence"] if item["sentence_indexes"] == [1, 2])
    assert (run["post_id"], run["start"], run["end"]) == ("dpo:99999:1003", 0, len(synthetic_thread.posts[2].text))

    assert decrack["code"][1]["pr"] == 42
    assert decrack["code"][1]["strength"] == "historical"
    assert decrack["code"][0]["commit"] is None
    source_ids = {source["id"] for source in data["sources"]}
    assert len(source_ids) == 8
    assert {item["source"] for item in decrack["evidence"]} <= source_ids
    assert set(FOOTNOTE_DEF.findall(body)) == source_ids


def test_frontmatter_escapes_awkward_text(sample_record):
    yaml = pytest.importorskip("yaml")
    question = 'Use "quotes": yes/no? # not a comment\nsecond line   and é \\ done'
    record = sample_record.model_copy(update={"question": question})
    front, _ = split_front(render_record(record))
    data = yaml.safe_load(front)
    assert data["decrack"]["question"] == question
    assert data["title"] == 'Use "quotes": yes/no? # not a comment second line and é \\ done'
