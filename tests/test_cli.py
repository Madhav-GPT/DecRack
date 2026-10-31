"""CLI: the commands through Typer's CliRunner, with a scripted model and a tmp database."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import decrack.cli as cli
from decrack.models import make_record_id
from decrack.pipeline.llm import ScriptedLLM
from decrack.search import NOTICE
from decrack.store import Store

runner = CliRunner()

# One sentence per post, so p1.s1, p2.s1 and p3.s1 certainly exist.
POSTS = [
    {"author": "alice", "text": "I propose a lazy keyword for imports."},
    {"author": "bob", "text": "Why not use a decorator instead of a keyword?"},
    {"author": "alice", "text": "We reject the decorator because it cannot apply to imports."},
]
THREAD_ID = "file:lazy-imports"
RECORD_ID = make_record_id(THREAD_ID)


def map_response(messages: list[dict]) -> dict:
    return {
        "items": [
            {
                "alt_ref": "new",
                "alternative": "Lazy keyword for imports",
                "act": "propose",
                "evidence_type": "proposal",
                "reason": "",
                "cites": ["p1.s1"],
            },
            {
                "alt_ref": "new",
                "alternative": "Use a decorator",
                "act": "propose",
                "evidence_type": "proposal",
                "reason": "",
                "cites": ["p2.s1"],
            },
            {
                "alt_ref": "new",
                "alternative": "Use a decorator",
                "act": "reject",
                "evidence_type": "decision_statement",
                "reason": "It cannot apply to imports.",
                "cites": ["p3.s1"],
            },
        ]
    }


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A tmp project folder with decrack.toml, a discussion file and a scripted model.

    The optional model steps (merge, refine_reasons, support) are off, so "map" is the only step called.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECRACK_DB", raising=False)
    monkeypatch.delenv("DECRACK_LLM", raising=False)
    (tmp_path / "decrack.toml").write_text(
        "[decrack]\nmerge_with_llm = false\nrefine_reasons = false\nsupport_check = false\n", encoding="utf-8"
    )
    (tmp_path / "lazy-imports.json").write_text(json.dumps(POSTS), encoding="utf-8")
    monkeypatch.setattr(cli, "make_llm", lambda settings, store=None: ScriptedLLM({"map": map_response}))
    return tmp_path


@pytest.fixture
def saved_sample(workdir, synthetic_thread, sample_record):
    with Store(workdir / "t.db") as store:
        store.save_thread(synthetic_thread)
        store.save_record(sample_record)
    return sample_record


def invoke(workdir, *args: str):
    return runner.invoke(cli.app, ["--db", str(workdir / "t.db"), *args])


def test_run_writes_example_then_why_and_verify(workdir):
    result = invoke(workdir, "run", str(workdir / "lazy-imports.json"), "--out", "out")
    assert result.exit_code == 0, result.output
    assert "Wrote" in result.output
    assert str(Path("out") / "run.json") in result.output
    thread = json.loads((workdir / "out" / "thread.json").read_text(encoding="utf-8"))
    records = json.loads((workdir / "out" / "records.json").read_text(encoding="utf-8"))
    run = json.loads((workdir / "out" / "run.json").read_text(encoding="utf-8"))
    assert thread["id"] == THREAD_ID
    assert len(thread["posts"]) == 3
    # Roles are assigned before the thread is stored and written.
    assert thread["posts"][0]["role"] == "author"
    assert all(post["role"] != "unknown" for post in thread["posts"])
    assert isinstance(records, list) and len(records) == 1
    assert records[0]["id"] == RECORD_ID
    assert records[0]["thread_id"] == THREAD_ID
    # run.json is the record's run block; a scripted run says so.
    assert run == records[0]["run"]
    assert (run["mode"], run["model"]) == ("scripted", "scripted")

    why = invoke(workdir, "why", "decorator")
    assert why.exit_code == 0, why.output
    assert NOTICE in why.output
    assert RECORD_ID in why.output

    verified = invoke(workdir, "verify", "out")
    assert verified.exit_code == 0, verified.output


def test_ingest_then_extract(workdir):
    ingested = invoke(workdir, "ingest", str(workdir / "lazy-imports.json"))
    assert ingested.exit_code == 0, ingested.output
    result = invoke(workdir, "extract", THREAD_ID)
    assert result.exit_code == 0, result.output
    with Store(workdir / "t.db") as store:
        assert store.get_record(RECORD_ID) is not None


def test_extract_unknown_thread(workdir):
    result = invoke(workdir, "extract", "file:nothing")
    assert result.exit_code == 1
    assert "no stored thread 'file:nothing'" in result.output


def test_db_option_is_respected(workdir):
    custom = workdir / "custom.db"
    result = runner.invoke(cli.app, ["--db", str(custom), "ingest", str(workdir / "lazy-imports.json")])
    assert result.exit_code == 0, result.output
    assert f"Stored {THREAD_ID}: 3 posts" in result.output
    assert custom.exists()
    assert not (workdir / "decrack.db").exists()
    with Store(custom) as store:
        thread = store.load_thread(THREAD_ID)
    assert thread is not None
    assert thread.posts[0].role == "author"


def test_source_error_exits_1_without_traceback(workdir, monkeypatch):
    def broken(ref, settings=None, client=None):
        raise ValueError(f"unsupported source: {ref}")

    monkeypatch.setattr(cli, "load_source", broken)
    result = invoke(workdir, "ingest", "nope")
    assert result.exit_code == 1
    assert "error: ValueError: unsupported source: nope" in result.output
    assert isinstance(result.exception, SystemExit)


def test_model_error_exits_1(workdir, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda settings, store=None: ScriptedLLM({}))
    result = invoke(workdir, "run", str(workdir / "lazy-imports.json"))
    assert result.exit_code == 1
    assert "LLMError" in result.output
    assert isinstance(result.exception, SystemExit)


def test_why_no_match(workdir):
    result = invoke(workdir, "why", "qwertyzzz")
    assert result.exit_code == 0, result.output
    assert 'No recorded decisions match "qwertyzzz".' in result.output


def test_why_by_path(saved_sample, workdir):
    result = invoke(workdir, "why", "Lib/widgets.py")
    assert result.exit_code == 0, result.output
    assert saved_sample.id in result.output


def test_check_pr_paths(saved_sample, workdir):
    result = invoke(workdir, "check-pr", "--paths", "Lib/widgets.py,Doc/other.rst", "--paths", "Lib/lazy.py")
    assert result.exit_code == 0, result.output
    assert "widgets" in result.output.lower()

    as_json = invoke(workdir, "check-pr", "--paths", "Lib/widgets.py", "--format", "json")
    assert as_json.exit_code == 0, as_json.output
    data = json.loads(as_json.stdout)
    assert {"paths", "prs", "matches", "markdown"} <= set(data)
    assert data["matches"]


def test_check_pr_wording_is_history_not_a_verdict(saved_sample, workdir):
    result = invoke(workdir, "check-pr", "--paths", "Lib/widgets.py", "--description", "use a decorator")
    assert result.exit_code == 0, result.output
    text = result.output.lower()
    assert "related history / possible conflict" in text
    assert "possible conflict" in text
    assert "invalid" not in text
    assert "violat" not in text


def test_search_evidence(saved_sample, workdir):
    result = invoke(workdir, "search-evidence", "decorator", "--limit", "3")
    assert result.exit_code == 0, result.output
    assert NOTICE in result.output
    assert "uncompiled" in result.output.lower()
    assert "decorator" in result.output.lower()

    nothing = invoke(workdir, "search-evidence", "qwertyzzz")
    assert nothing.exit_code == 0, nothing.output
    assert 'No stored posts match "qwertyzzz".' in nothing.output


def test_check_pr_needs_input(workdir):
    result = invoke(workdir, "check-pr")
    assert result.exit_code == 2
    assert "give a PR URL" in result.output


def test_check_pr_rejects_unknown_format(workdir):
    result = invoke(workdir, "check-pr", "--paths", "Lib/widgets.py", "--format", "xml")
    assert result.exit_code == 2


def test_export_okf(saved_sample, workdir):
    result = invoke(workdir, "export", "okf", "--out", "bundle")
    assert result.exit_code == 0, result.output
    assert "Exported 1 decision records" in result.output
    assert (workdir / "bundle" / "index.md").is_file()


def test_export_calls(workdir):
    with Store(workdir / "t.db") as store:
        request = {"model": "qwen3.5:4b", "step": "map", "messages": []}
        store.put_llm_call("k1", "map", "qwen3.5:4b", request, {"items": []})
    target = workdir / "calls" / "calls.jsonl"
    result = invoke(workdir, "export", "calls", "--out", str(target))
    assert result.exit_code == 0, result.output
    assert "Exported 1 model calls" in result.output
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["key"] == "k1"


def test_verify_empty_dir(workdir):
    (workdir / "empty").mkdir()
    result = invoke(workdir, "verify", "empty")
    assert result.exit_code == 0, result.output


def test_verify_missing_dir(workdir):
    assert invoke(workdir, "verify", "nowhere").exit_code == 2


def test_doctor_gets_global_options(workdir, monkeypatch):
    def fake_doctor(settings):
        return [f"[ok] db={settings.db_path} model={settings.model} host={settings.ollama_host}"], 0

    monkeypatch.setattr(cli, "run_doctor", fake_doctor)
    db = str(workdir / "t.db")
    args = ["--db", db, "--model", "gemma4:e4b", "--ollama-host", "http://10.0.0.5:11434/", "doctor"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert f"[ok] db={db} model=gemma4:e4b host=http://10.0.0.5:11434" in result.output.splitlines()


def test_doctor_exit_code(workdir, monkeypatch):
    monkeypatch.setattr(cli, "run_doctor", lambda settings: (["[missing] Ollama is not reachable"], 1))
    result = invoke(workdir, "doctor")
    assert result.exit_code == 1
    assert "[missing] Ollama is not reachable" in result.output


def test_eval_rejects_bad_ref(workdir):
    result = invoke(workdir, "eval", "pep:830", "notapep")
    assert result.exit_code == 1
    assert "'notapep' is not a PEP reference" in result.output


def test_eval_writes_to_examples_runs_by_default(workdir, monkeypatch, synthetic_thread):
    gold = {
        "pep": 9999,
        "title": "Lazy widgets",
        "items": [{"id": "pep9999-r1", "idea": "Using a decorator", "reason": "It cannot apply to imports."}],
    }
    (workdir / "eval" / "gold").mkdir(parents=True)
    (workdir / "eval" / "gold" / "pep-9999.json").write_text(json.dumps(gold), encoding="utf-8")
    loaded = []

    def fake_load(ref, settings=None, client=None):
        loaded.append((ref, settings.eval_mode))
        return synthetic_thread

    monkeypatch.setattr("decrack.sources.load", fake_load)  # no network: the PEP's discussion is the fixture
    result = invoke(workdir, "eval", "pep:9999")
    assert result.exit_code == 0, result.output
    assert loaded == [("pep:9999", True)]  # the leak guard is on while loading
    runs = workdir / "examples" / "runs"
    for name in ("thread.json", "records.json", "run.json", "scores.json"):
        assert (runs / "pep-9999" / name).is_file()
    assert (runs / "eval-summary.md").is_file()
    assert (runs / "eval-summary.json").is_file()
    assert f"Wrote {Path('examples') / 'runs' / 'eval-summary.md'}" in result.output
    assert "# Withheld-PEP evaluation" in result.output


def test_pep_number():
    assert cli.pep_number("pep:830") == 830
    assert cli.pep_number("PEP 830") == 830
    assert cli.pep_number("830") == 830
    assert cli.pep_number("pep-0830") == 830
    assert cli.pep_number("notapep") is None
    assert cli.pep_number("pep:abc") is None
