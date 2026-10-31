"""doctor: Ollama /api/tags checks through a mock transport, the OpenCode snippet and the uvx alternative."""

import json
import shlex
from pathlib import Path

import httpx
import pytest

from decrack.config import DEFAULT_MODEL, Settings
from decrack.doctor import has_model, opencode_snippet, run_doctor, uvx_command

GIT_SOURCE = "git+https://github.com/Madhav-GPT/DecRack"


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
    lines, code = run_doctor(settings, client=tags_client([DEFAULT_MODEL, "gemma4:e4b"]))
    assert code == 0
    assert f"[ok] model {DEFAULT_MODEL} is installed" in lines
    assert any(line.startswith("[ok] Ollama is running") for line in lines)
    # A missing opencode is reported but does not fail the check.
    assert any(line.startswith("[missing] opencode") for line in lines)


def test_model_missing(settings):
    lines, code = run_doctor(settings, client=tags_client(["gemma4:e4b"]))
    assert code == 1
    assert any(f"ollama pull {DEFAULT_MODEL}" in line for line in lines)
    assert any(line.startswith(f"[missing] model {DEFAULT_MODEL}") for line in lines)


def test_untagged_model_means_latest(settings):
    lines, code = run_doctor(settings.model_copy(update={"model": "mymodel"}), client=tags_client(["mymodel:latest"]))
    assert code == 0
    assert "[ok] model mymodel is installed" in lines
    assert has_model("qwen3.5:4b", ["qwen3.5:4b"])
    assert not has_model("qwen3.5:4b", ["qwen3.5:9b"])
    assert not has_model("qwen3.5:4b", ["qwen3.5:latest"])


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


def test_doctor_prints_snippet_and_the_uvx_alternative(settings, tmp_path):
    lines, _ = run_doctor(settings, client=tags_client([DEFAULT_MODEL]))
    start = lines.index("{")
    end = lines.index("}", start)  # json.dumps(indent=2) closes the outer object on a line of its own
    config = json.loads("\n".join(lines[start : end + 1]))
    command = config["mcp"]["decrack"]["command"]
    assert command[:3] == ["uv", "run", "--directory"]
    assert command[-1] == "mcp"

    db = str((tmp_path / "t.db").resolve())
    alternatives = [line for line in lines[end + 1 :] if line.startswith("uvx ")]
    assert len(alternatives) == 1
    assert shlex.split(alternatives[0]) == ["uvx", "--from", GIT_SOURCE, "decrack", "--db", db, "mcp"]
    # DecRack is installed from its repository; the doctor never points at a package index.
    assert not any("pypi" in line.lower() for line in lines)


def test_opencode_snippet(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = json.loads(opencode_snippet(Settings(db_path="t.db")))
    assert config["$schema"] == "https://opencode.ai/config.json"
    server = config["mcp"]["decrack"]
    assert server["type"] == "local"
    assert server["enabled"] is True
    command = server["command"]
    assert command[:3] == ["uv", "run", "--directory"]
    assert Path(command[3]).is_absolute()
    assert command[-1] == "mcp"
    db = Path(command[command.index("--db") + 1])
    assert db.is_absolute()
    assert db == (tmp_path / "t.db").resolve()
    assert "--model" not in command
    assert "--ollama-host" not in command


def test_opencode_snippet_with_other_model(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    command = json.loads(opencode_snippet(Settings(db_path="t.db", model="gemma4:e4b")))["mcp"]["decrack"]["command"]
    assert command[-3:] == ["--model", "gemma4:e4b", "mcp"]


def test_uvx_command_carries_the_same_options(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(db_path="t.db", model="gemma4:e4b", ollama_host="http://10.0.0.5:11434")
    command = uvx_command(settings)
    assert command[:4] == ["uvx", "--from", GIT_SOURCE, "decrack"]
    assert command[4:] == [
        "--db",
        str((tmp_path / "t.db").resolve()),
        "--model",
        "gemma4:e4b",
        "--ollama-host",
        "http://10.0.0.5:11434",
        "mcp",
    ]
    # The snippet runs the same decrack arguments from this clone.
    snippet = json.loads(opencode_snippet(settings))["mcp"]["decrack"]["command"]
    assert snippet[4:] == command[3:]
