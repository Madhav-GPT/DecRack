"""CLI: the commands through Typer's CliRunner, with a scripted model and a tmp database."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import decrack.cli as cli
from decrack import linking
from decrack.models import make_record_id
from decrack.pipeline.llm import LLMError, ScriptedLLM
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
    """A tmp project folder with a discussion file and a scripted model.

    The optional support check is off by default, so "map" is the only model step called.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECRACK_DB", raising=False)
    monkeypatch.delenv("DECRACK_LLM", raising=False)
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


def test_a_source_that_cannot_be_read_stops_at_the_fetch_gate(workdir, monkeypatch):
    def broken(ref, settings=None, client=None):
        raise ValueError(f"unsupported source: {ref}")

    monkeypatch.setattr(cli, "load_source", broken)
    result = invoke(workdir, "ingest", "pep:1")
    assert result.exit_code == 4
    assert "Could not read this discussion: unsupported source: pep:1" in result.output
    assert isinstance(result.exception, SystemExit)
    assert not (workdir / "t.db").exists()  # nothing stored


def test_model_error_exits_1(workdir, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda settings, store=None: ScriptedLLM({}))
    result = invoke(workdir, "run", str(workdir / "lazy-imports.json"))
    assert result.exit_code == 1
    assert "LLMError" in result.output
    assert isinstance(result.exception, SystemExit)


def test_why_no_match(saved_sample, workdir):
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


def test_why_raw_searches_the_uncompiled_posts(saved_sample, workdir):
    result = invoke(workdir, "why", "decorator", "--raw", "--limit", "3")
    assert result.exit_code == 0, result.output
    assert NOTICE in result.output
    assert "uncompiled" in result.output.lower()
    assert "decorator" in result.output.lower()

    nothing = invoke(workdir, "why", "qwertyzzz", "--raw")
    assert nothing.exit_code == 0, nothing.output
    assert 'No stored posts match "qwertyzzz".' in nothing.output


def test_check_pr_diff_blames_only_with_the_flag(saved_sample, workdir, monkeypatch):
    def no_blame(repo_dir, base, head):
        raise AssertionError("prs_for_change must not run without --blame")

    monkeypatch.setattr(linking, "changed_files", lambda repo_dir, base, head: ["Lib/widgets.py"])
    monkeypatch.setattr(linking, "follow_renames", lambda repo_dir, path: [path])
    monkeypatch.setattr(linking, "origin_repo", lambda repo_dir: "example/widgets")
    monkeypatch.setattr(linking, "prs_for_change", no_blame)
    result = invoke(workdir, "check-pr", "--diff", "main..feature", "--format", "json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["paths"] == ["Lib/widgets.py"]
    assert data["prs"] == []
    assert data["matches"]

    blamed: list[tuple[str, str]] = []

    def blame_walk(repo_dir, base, head):
        blamed.append((base, head))
        return ["Lib/widgets.py"], [42]

    monkeypatch.setattr(linking, "prs_for_change", blame_walk)
    result = invoke(workdir, "check-pr", "--diff", "main..feature", "--blame", "--format", "json")
    assert result.exit_code == 0, result.output
    assert blamed == [("main", "feature")]
    assert json.loads(result.stdout)["prs"] == [42]


def test_check_pr_needs_input(workdir):
    result = invoke(workdir, "check-pr")
    assert result.exit_code == 2
    assert "Give a PR URL, --paths, or --diff." in result.output


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
        request = {"model": "qwen2.5:1.5b", "step": "map", "messages": []}
        store.put_llm_call("k1", "map", "qwen2.5:1.5b", request, {"items": []})
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
    args = ["--db", db, "--model", "test-model:b", "--ollama-host", "http://10.0.0.5:11434/", "doctor"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert f"[ok] db={db} model=test-model:b host=http://10.0.0.5:11434" in result.output.splitlines()


def test_support_check_flag_turns_the_check_on(workdir, monkeypatch):
    """--support-check is a global option; without it the check stays off."""
    seen: list[bool] = []

    def capture(settings, store=None):
        seen.append(settings.support_check)
        raise LLMError("stop once the settings are seen")

    monkeypatch.setattr(cli, "make_llm", capture)
    source = str(workdir / "lazy-imports.json")
    assert invoke(workdir, "--support-check", "run", source, "--out", "out").exit_code == 1
    assert invoke(workdir, "run", source, "--out", "out").exit_code == 1
    assert seen == [True, False]


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
    for name in ("thread.json", "records.json", "run.json", "scores.json", "matches.json"):
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


def test_show_a_decision_at_each_detail(saved_sample, workdir):
    card = invoke(workdir, "show", saved_sample.id)
    assert card.exit_code == 0, card.output
    assert NOTICE in card.output
    assert saved_sample.id in card.output

    full = invoke(workdir, "show", saved_sample.id, "--detail", "full")
    assert full.exit_code == 0, full.output
    assert "We rejected the decorator approach" in full.output  # quotes, word for word

    evidence = invoke(workdir, "show", saved_sample.id, "--detail", "evidence")
    assert evidence.exit_code == 0, evidence.output
    assert "I propose PEP 9999 to add lazy widgets" in evidence.output  # the reply parent of the cited posts

    as_json = invoke(workdir, "show", saved_sample.id, "--format", "json")
    assert as_json.exit_code == 0, as_json.output
    data = json.loads(as_json.stdout)
    assert (data["ok"], data["decision_id"], data["detail"]) == (True, saved_sample.id, "card")
    assert {"key", "title", "status", "status_kind", "confidence", "reason", "link"} <= set(data["card"]["options"][0])

    by_thread = invoke(workdir, "show", "pep:9999", "--detail", "full", "--format", "json")
    assert json.loads(by_thread.stdout)["record"]["id"] == saved_sample.id

    missing = invoke(workdir, "show", "dr-00000000")
    assert missing.exit_code == 1
    assert "No decision 'dr-00000000' is recorded." in missing.output
    assert invoke(workdir, "show", saved_sample.id, "--detail", "everything").exit_code == 2


def test_why_json_returns_compact_cards(saved_sample, workdir):
    result = invoke(workdir, "why", "decorator", "--format", "json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert (data["ok"], data["query"], data["raw"]) == (True, "decorator", False)
    [card] = data["results"]
    assert card["decision_id"] == saved_sample.id
    assert card["link"] == saved_sample.thread_url
    assert {option["status_kind"] for option in card["options"]} == {"confirmed"}

    by_path = json.loads(invoke(workdir, "why", "Lib/widgets.py", "--format", "json").stdout)
    assert [card["decision_id"] for card in by_path["results"]] == [saved_sample.id]

    raw = json.loads(invoke(workdir, "why", "decorator", "--raw", "--format", "json").stdout)
    assert raw["ok"] is True and raw["raw"] is True and raw["results"]


def test_the_cli_has_no_mcp_command(workdir):
    assert invoke(workdir, "mcp").exit_code == 2  # unknown command
