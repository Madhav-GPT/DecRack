"""doctor: Ollama /api/tags checks through a mock transport, and the agent hint it ends with."""

import httpx
import pytest

from decrack.config import DEFAULT_MODEL, Settings
from decrack.doctor import AGENT_HINT, has_model, run_doctor

def tags_client(names: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": name, "model": name} for name in names]})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    # Whether opencode is installed on the test machine must not matter.
    monkeypatch.setattr("decrack.doctor.shutil.which", lambda name: None)
    return Settings(db_path=str(tmp_path / "t.db"))


def test_model_installed(settings):
    lines, code = run_doctor(settings, client=tags_client([DEFAULT_MODEL, "test-model:b"]))
    assert code == 0
    assert f"[ok] model {DEFAULT_MODEL} is installed" in lines
    assert any(line.startswith("[ok] Ollama is running") for line in lines)
    # A missing opencode is reported but does not fail the check.
    assert any(line.startswith("[missing] opencode") for line in lines)


def test_model_missing(settings):
    lines, code = run_doctor(settings, client=tags_client(["test-model:b"]))
    assert code == 1
    assert any(f"ollama pull {DEFAULT_MODEL}" in line for line in lines)
    assert any(line.startswith(f"[missing] model {DEFAULT_MODEL}") for line in lines)


def test_untagged_model_means_latest(settings):
    lines, code = run_doctor(settings.model_copy(update={"model": "mymodel"}), client=tags_client(["mymodel:latest"]))
    assert code == 0
    assert "[ok] model mymodel is installed" in lines
    assert has_model("qwen2.5:1.5b", ["qwen2.5:1.5b"])
    assert not has_model("qwen2.5:1.5b", ["test-model:b"])
    assert not has_model("qwen2.5:1.5b", ["qwen2.5:latest"])


def test_ollama_unreachable(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    lines, code = run_doctor(settings, client=client)
    assert code == 1
    assert any("not reachable" in line and "http://127.0.0.1:11434" in line for line in lines)


def test_ollama_answers_with_error_status(settings):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    lines, code = run_doctor(settings, client=client)
    assert code == 1
    assert any("HTTP 404" in line for line in lines)


def test_doctor_ends_with_the_agent_hint(settings):
    lines, _ = run_doctor(settings, client=tags_client([DEFAULT_MODEL]))
    assert lines[-1] == AGENT_HINT
    assert "decrack why" in AGENT_HINT and "--format json" in AGENT_HINT
    # DecRack is used through its CLI: no MCP config, and no package index.
    assert not any("mcp" in line.lower() or "pypi" in line.lower() for line in lines)
