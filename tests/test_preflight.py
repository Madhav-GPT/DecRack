"""Preflight gates: each one stops with one plain sentence before any work, without network or model."""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from decrack import cli, preflight
from decrack.config import DEFAULT_MODEL, Settings
from decrack.models import Post, Thread
from decrack.pipeline.llm import ScriptedLLM
from decrack.store import Store

runner = CliRunner()


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECRACK_DB", raising=False)
    monkeypatch.delenv("DECRACK_LLM", raising=False)
    # A scripted model with no answers: any model call would fail the test.
    monkeypatch.setattr(cli, "make_llm", lambda settings, store=None: ScriptedLLM({}))
    return tmp_path


def invoke(workdir, *args: str):
    return runner.invoke(cli.app, ["--db", str(workdir / "t.db"), *args])


def tags_client(names: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": name} for name in names]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def empty_thread() -> Thread:
    return Thread(id="pep:1", kind="discourse", title="Blanked", posts=[Post(id="dpo:1:1", seq=1, author="a")])


# 1. Source gate ------------------------------------------------------------------------


def test_source_gate_accepts_the_known_forms(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("We decided against it.", encoding="utf-8")
    assert preflight.check_source("pep:830") == "pep"
    assert preflight.check_source("https://github.com/python/cpython/issues/12345") == "github"
    assert preflight.check_source("python/cpython#12345") == "github"
    assert preflight.check_source("https://discuss.python.org/t/pep-830/106942") == "discourse"
    assert preflight.check_source(str(notes)) == "file"
    for bad in (None, "", "   ", "hello world", "missing.json", "https://example.org/page"):
        with pytest.raises(preflight.GateError) as info:
            preflight.check_source(bad)
        assert (info.value.error, info.value.code) == (preflight.SOURCE_HELP, 2)


def test_run_without_a_usable_source_stores_nothing(workdir):
    result = invoke(workdir, "run", "hello world")
    assert result.exit_code == 2
    assert result.output.strip() == preflight.SOURCE_HELP
    assert not (workdir / "t.db").exists()


# 2. Model gate -------------------------------------------------------------------------


def test_model_gate():
    settings = Settings()
    preflight.check_model(settings, client=tags_client([DEFAULT_MODEL]))
    with pytest.raises(preflight.GateError) as info:
        preflight.check_model(settings, client=tags_client(["test-model:b"]))
    assert info.value.code == 3
    assert f"ollama pull {DEFAULT_MODEL}" in info.value.text()

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(preflight.GateError) as info:
        preflight.check_model(settings, client=httpx.Client(transport=httpx.MockTransport(refuse)))
    assert info.value.code == 3
    assert "ollama serve" in info.value.text()


def test_only_a_live_model_is_checked():
    assert not preflight.needs_model_check(ScriptedLLM({}))

    class Live:
        mode = "live"

    assert preflight.needs_model_check(Live())


# 3. Fetch gate -------------------------------------------------------------------------


def test_fetch_gate_explains_each_failure():
    def failing(error: Exception):
        def loader(ref, settings):
            raise error

        return loader

    cases = [
        (
            ValueError("GitHub issue or pull request o/r#1 was not found (HTTP 404 for https://x)."),
            "GitHub returned 404: the URL is wrong or the repo is private. DecRack reads public data only.",
        ),
        (
            RuntimeError("GitHub refused https://x with HTTP 403: the GitHub rate limit was hit."),
            "GitHub rate limit reached. Set GITHUB_TOKEN to a read-only token.",
        ),
        (
            httpx.ConnectError("refused", request=httpx.Request("GET", "https://discuss.python.org/t/1.json")),
            "Could not reach the server. Check your network connection and retry.",
        ),
    ]
    for error, text in cases:
        with pytest.raises(preflight.GateError) as info:
            preflight.fetch("o/r#1", Settings(), failing(error))
        assert (info.value.text(), info.value.code) == (text, 4)


# 4. Content gate -----------------------------------------------------------------------


def test_nothing_to_analyze_stops_before_the_model(workdir, monkeypatch):
    with pytest.raises(preflight.GateError) as info:
        preflight.check_content(empty_thread())
    assert (info.value.error, info.value.code) == (preflight.NOTHING_TO_ANALYZE, 0)

    monkeypatch.setattr(cli, "load_source", lambda ref, settings=None, client=None: empty_thread())
    result = invoke(workdir, "run", "pep:1")
    assert result.exit_code == 0, result.output
    assert "Nothing to analyze in this discussion." in result.output
    with Store(workdir / "t.db") as store:
        assert store.load_thread("pep:1") is None  # nothing stored


# 5. Query gates ------------------------------------------------------------------------


def test_query_gates(workdir):
    empty_query = invoke(workdir, "why", "  ")
    assert empty_query.exit_code == 2
    assert "Ask a question, or give a file path." in empty_query.output

    empty_db = invoke(workdir, "why", "decorator")
    assert empty_db.exit_code == 1
    assert "No decisions recorded yet. Run `decrack run <URL>` first." in empty_db.output

    no_change = invoke(workdir, "check-pr")
    assert no_change.exit_code == 2
    assert "Give a PR URL, --paths, or --diff." in no_change.output


def test_json_mode_returns_the_error_object(workdir):
    result = invoke(workdir, "check-pr", "--format", "json")
    assert result.exit_code == 2
    assert json.loads(result.stdout) == {"ok": False, "error": preflight.CHANGE_INPUT, "fix": ""}

    empty_db = invoke(workdir, "check-pr", "--paths", "Lib/widgets.py", "--format", "json")
    assert empty_db.exit_code == 1
    assert json.loads(empty_db.stdout)["error"] == preflight.EMPTY_DB


def test_why_json_mode_gives_the_error_object(workdir):
    empty_query = invoke(workdir, "why", "", "--format", "json")
    assert empty_query.exit_code == 2
    assert json.loads(empty_query.stdout) == {"ok": False, "error": preflight.EMPTY_QUERY, "fix": ""}

    empty_db = invoke(workdir, "why", "decorator", "--format", "json")
    assert empty_db.exit_code == 1
    assert json.loads(empty_db.stdout) == {"ok": False, "error": preflight.EMPTY_DB, "fix": ""}


def test_show_json_mode_gives_the_error_object(workdir):
    result = invoke(workdir, "show", "dr-00000000", "--format", "json")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == preflight.EMPTY_DB
