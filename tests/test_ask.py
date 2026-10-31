"""decrack ask: a question about one discussion, or about a repo's best-matching issues and PRs.

The GitHub search API is a MockTransport; the threads and their records are the shared
fixtures, so no test touches the network or a model.
"""

from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

import decrack.cli as cli
from decrack import preflight
from decrack.ask import ASK_HELP
from decrack.models import make_record_id
from decrack.pipeline.llm import ScriptedLLM

runner = CliRunner()
REPO = "https://github.com/example/widgets"
QUESTION = "Why not a decorator keyword?"


@pytest.fixture
def workdir(tmp_path, monkeypatch, synthetic_thread, sample_record):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECRACK_DB", raising=False)
    monkeypatch.delenv("DECRACK_LLM", raising=False)
    monkeypatch.setattr(cli, "make_llm", lambda settings, store=None: ScriptedLLM({}))

    def load(ref, settings=None, client=None):
        # A copy of the synthetic thread per URL, so every search hit is a thread of its own.
        number = ref.rstrip("/").rsplit("/", 1)[-1]
        thread_id = f"gh:example/widgets#{number}" if "github.com" in ref else synthetic_thread.id
        return synthetic_thread.model_copy(update={"id": thread_id, "url": ref})

    def compile_stub(thread, llm, settings, progress=None):
        update = {"id": make_record_id(thread.id), "thread_id": thread.id, "thread_url": thread.url}
        return sample_record.model_copy(update=update)

    monkeypatch.setattr(cli, "load_source", load)
    monkeypatch.setattr(cli, "compile_thread", compile_stub)
    return tmp_path


def invoke(workdir, *args: str):
    return runner.invoke(cli.app, ["--db", str(workdir / "t.db"), *args])


def use_search(monkeypatch, items: list[dict]) -> list[httpx.Request]:
    """Answer GitHub's search API with ``items``; return the requests it saw."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/search/issues"
        return httpx.Response(200, json={"total_count": len(items), "items": items})

    monkeypatch.setattr(cli, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return seen


def no_search(monkeypatch) -> None:
    def refuse():
        raise AssertionError("the search API must not be called")

    monkeypatch.setattr(cli, "make_client", refuse)


def test_a_repo_question_reads_the_top_matching_threads(workdir, monkeypatch):
    seen = use_search(monkeypatch, [{"html_url": f"{REPO}/issues/7"}, {"html_url": f"{REPO}/pull/8"}])
    result = invoke(workdir, "ask", REPO, QUESTION)
    assert result.exit_code == 0, result.output
    assert seen[0].url.params["q"] == "repo:example/widgets decorator keyword"  # stopwords dropped
    assert seen[0].url.params["per_page"] == "3"
    assert f"Read 2 thread(s): {REPO}/issues/7, {REPO}/pull/8" in result.output
    assert make_record_id("gh:example/widgets#7") in result.output
    assert make_record_id("gh:example/widgets#8") in result.output

    as_json = json.loads(invoke(workdir, "ask", REPO, QUESTION, "--format", "json").stdout)
    assert as_json["ok"] is True
    assert as_json["keywords"] == ["decorator", "keyword"]
    assert [thread["url"] for thread in as_json["threads"]] == [f"{REPO}/issues/7", f"{REPO}/pull/8"]
    assert {card["decision_id"] for card in as_json["results"]} == {
        make_record_id("gh:example/widgets#7"),
        make_record_id("gh:example/widgets#8"),
    }


def test_max_threads_limits_the_search(workdir, monkeypatch):
    seen = use_search(monkeypatch, [{"html_url": f"{REPO}/issues/7"}])
    result = invoke(workdir, "ask", REPO, QUESTION, "--max-threads", "1")
    assert result.exit_code == 0, result.output
    assert seen[0].url.params["per_page"] == "1"
    assert invoke(workdir, "ask", REPO, QUESTION, "--max-threads", "6").exit_code == 2  # at most 5


def test_a_repo_question_with_no_matches(workdir, monkeypatch):
    use_search(monkeypatch, [])
    result = invoke(workdir, "ask", REPO, QUESTION)
    assert result.exit_code == 1
    assert (
        "No issues or PRs in example/widgets match: decorator keyword. Try other words, or give an issue URL."
        in result.output
    )


def test_a_repo_url_needs_a_question(workdir, monkeypatch):
    no_search(monkeypatch)
    result = invoke(workdir, "ask", REPO)
    assert result.exit_code == 2
    assert ASK_HELP in result.output
    as_json = invoke(workdir, "ask", REPO, "--format", "json")
    assert json.loads(as_json.stdout) == {"ok": False, "error": ASK_HELP, "fix": ""}


def test_asking_about_one_discussion_skips_the_search(workdir, monkeypatch):
    no_search(monkeypatch)
    result = invoke(workdir, "ask", "pep:9999", "decorator")
    assert result.exit_code == 0, result.output
    assert "Read 1 thread(s):" in result.output
    assert make_record_id("pep:9999") in result.output


def test_the_model_gate_runs_before_the_search(workdir, monkeypatch):
    no_search(monkeypatch)

    class Live:
        mode = "live"

    def down(settings, client=None):  # pick_model: Ollama does not answer
        raise preflight.GateError("Ollama is not reachable.", "Start it with `ollama serve`.", 3)

    monkeypatch.setattr(cli, "make_llm", lambda settings, store=None: Live())
    monkeypatch.setattr(preflight, "pick_model", down)
    result = invoke(workdir, "ask", REPO, QUESTION)
    assert result.exit_code == 3
    assert "ollama serve" in result.output


def test_an_unknown_source_is_refused(workdir, monkeypatch):
    no_search(monkeypatch)
    result = invoke(workdir, "ask", "hello world", "why?")
    assert result.exit_code == 2
    assert preflight.SOURCE_HELP in result.output
