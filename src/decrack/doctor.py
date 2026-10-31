"""``decrack doctor``: check the local setup without changing anything.

It asks the local Ollama server which models are installed, checks that the
configured model is one of them, looks for the ``opencode`` command, and ends
with a one-line hint on how a coding agent uses DecRack: through the CLI.
"""

from __future__ import annotations

import shutil
from typing import Any

import httpx

from decrack.config import Settings

OLLAMA_HINT = "Install it from https://ollama.com and run `ollama serve`."
OPENCODE_HINT = "Install it with `npm i -g opencode-ai` (see https://opencode.ai)."
TAGS_TIMEOUT = 5.0
AGENT_HINT = 'Tell your agent: run `decrack run <URL>`, then `decrack why "<question>" --format json`.'


def model_names(tags: Any) -> list[str]:
    """Installed model names from an ``/api/tags`` reply, such as ``["qwen2.5:1.5b"]``."""
    names: list[str] = []
    if not isinstance(tags, dict):
        return names
    for item in tags.get("models") or []:
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = item.get(key)
            if isinstance(value, str) and value and value not in names:
                names.append(value)
    return names


def has_model(model: str, installed: list[str]) -> bool:
    """True if ``model`` is installed. A name without a tag means ``<name>:latest``."""
    if model in installed:
        return True
    return ":" not in model and f"{model}:latest" in installed


def run_doctor(settings: Settings, client: httpx.Client | None = None) -> tuple[list[str], int]:
    """Check Ollama, the configured model and OpenCode; return (lines, exit code).

    The exit code is 1 when Ollama is unreachable or the model is missing.
    A missing ``opencode`` command is reported but does not fail the check.
    """
    host = settings.ollama_host.rstrip("/")
    model = settings.model
    lines: list[str] = []
    code = 0

    installed: list[str] | None = None
    http = client if client is not None else httpx.Client(timeout=TAGS_TIMEOUT)
    try:
        response = http.get(f"{host}/api/tags", timeout=TAGS_TIMEOUT)
        response.raise_for_status()
        installed = model_names(response.json())
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        lines.append(f"[missing] {host} is not answering like Ollama (HTTP {status} from /api/tags). {OLLAMA_HINT}")
    except ValueError:
        lines.append(f"[missing] {host} is not answering like Ollama (/api/tags did not return JSON). {OLLAMA_HINT}")
    except (httpx.HTTPError, httpx.InvalidURL):
        lines.append(f"[missing] Ollama is not reachable at {host}. {OLLAMA_HINT}")
    finally:
        if client is None:
            http.close()

    if installed is None:
        code = 1
        lines.append(f"[skip] model {model} was not checked. Once Ollama runs: ollama pull {model}")
    else:
        lines.append(f"[ok] Ollama is running at {host} with {len(installed)} model(s) installed")
        if has_model(model, installed):
            lines.append(f"[ok] model {model} is installed")
        else:
            code = 1
            lines.append(f"[missing] model {model} is not installed. Run: ollama pull {model}")

    opencode = shutil.which("opencode")
    if opencode:
        lines.append(f"[ok] opencode found at {opencode}")
    else:
        lines.append(f"[missing] opencode is not on PATH. {OPENCODE_HINT}")

    lines.append("")
    lines.append(AGENT_HINT)
    return lines, code
