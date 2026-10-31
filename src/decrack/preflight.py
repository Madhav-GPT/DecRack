"""Preflight gates: check what a command needs before doing any work.

Every gate either passes or stops the command with one plain sentence and its
fix. Gates run in order, and a command never moves past one that failed:

1. source: a discussion DecRack can read was given (exit code 2);
2. model: Ollama answers and the model is installed (exit code 3);
3. fetch: the discussion could be read (exit code 4);
4. content: it still has text to analyze (exit code 0: nothing to do);
5. query: a question, file path or change was given (exit code 2), and the
   store holds decisions to search (exit code 1).

The CLI prints ``error`` and ``fix``; with ``--format json`` callers
get ``{"ok": false, "error": ..., "fix": ...}`` instead.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from decrack import sources
from decrack.config import DEFAULT_MODEL, Settings
from decrack.doctor import has_model, model_names
from decrack.models import Thread

SOURCE_HELP = (
    "DecRack needs a discussion to read: a GitHub issue or PR URL, a discuss.python.org thread URL, "
    "pep:NNN, or a file path."
)
NOTHING_TO_ANALYZE = "Nothing to analyze in this discussion."
EMPTY_DB = "No decisions recorded yet. Run `decrack run <URL>` first."
EMPTY_QUERY = "Ask a question, or give a file path."
CHANGE_INPUT = "Give a PR URL, --paths, or --diff."
TAGS_TIMEOUT = 5.0
OLLAMA_DOWN = "Ollama isn't running. Install it from https://ollama.com/download, then run: ollama serve"
NO_MODEL = f"No open model installed. Run: ollama pull {DEFAULT_MODEL}"


class GateError(Exception):
    """A gate that did not pass: a plain message, how to fix it, and the CLI exit code."""

    def __init__(self, error: str, fix: str = "", code: int = 1) -> None:
        super().__init__(error)
        self.error = error
        self.fix = fix
        self.code = code

    def text(self) -> str:
        """``error`` and ``fix`` as one line for the terminal."""
        return f"{self.error} {self.fix}".strip()

    def as_json(self) -> str:
        return json.dumps({"ok": False, "error": self.error, "fix": self.fix})


def check_source(ref: str | None) -> str:
    """Gate 1: which connector reads ``ref`` ("pep", "github", "discourse" or "file"). No network."""
    value = (ref or "").strip()
    if value:
        try:
            return sources.detect(value)
        except (ValueError, OSError):
            pass
    raise GateError(SOURCE_HELP, code=2)


def needs_model_check(llm: Any) -> bool:
    """Only a live Ollama client needs gate 2; replayed and scripted answers do not."""
    return getattr(llm, "mode", "") == "live"


def check_model(settings: Settings, client: httpx.Client | None = None) -> None:
    """Gate 2: Ollama answers ``GET /api/tags`` and lists the configured model."""
    host, model = settings.ollama_host.rstrip("/"), settings.model
    http = client if client is not None else httpx.Client(timeout=TAGS_TIMEOUT)
    try:
        response = http.get(f"{host}/api/tags", timeout=TAGS_TIMEOUT)
        response.raise_for_status()
        installed = model_names(response.json())
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        raise GateError(
            f"Ollama is not reachable at {host}.",
            f"Start it with `ollama serve`, then run `ollama pull {model}`.",
            code=3,
        ) from None
    finally:
        if client is None:
            http.close()
    if not has_model(model, installed):
        raise GateError(f"The model {model} is not installed in Ollama.", f"Run `ollama pull {model}`.", code=3)


def installed_models(settings: Settings, client: httpx.Client | None = None) -> list[str]:
    """Names of the models the local Ollama lists (``GET /api/tags``); gate 2 fails when it does not answer."""
    http = client if client is not None else httpx.Client(timeout=TAGS_TIMEOUT)
    try:
        response = http.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=TAGS_TIMEOUT)
        response.raise_for_status()
        return model_names(response.json())
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        raise GateError(OLLAMA_DOWN, code=3) from None
    finally:
        if client is None:
            http.close()


def pick_model(settings: Settings, client: httpx.Client | None = None) -> str:
    """Gate 2 with auto-detect: the configured model if installed, else the default, else any local model.

    Only models Ollama runs on this machine count: names with "cloud" in them are skipped.
    """
    local = [name for name in installed_models(settings, client) if "cloud" not in name.lower()]
    for wanted in (settings.model, DEFAULT_MODEL):
        if has_model(wanted, local):
            return wanted
    if local:
        return local[0]
    raise GateError(NO_MODEL, code=3)


def using_line(model: str) -> str:
    return f"Using {model} (local, open-weight via Ollama)"


def fetch(ref: str, settings: Settings, loader: Callable[[str, Settings], Thread]) -> Thread:
    """Gate 3: read the discussion; every way that can fail becomes one plain sentence (exit code 4)."""
    try:
        return loader(ref, settings)
    except httpx.TimeoutException:
        raise GateError("The server took too long to answer.", "Check your network connection and retry.", 4) from None
    except httpx.TransportError:
        raise GateError("Could not reach the server.", "Check your network connection and retry.", 4) from None
    except httpx.HTTPStatusError as exc:
        status, host = exc.response.status_code, exc.request.url.host
        raise GateError(f"{host} returned HTTP {status}.", "Check the URL, or retry later.", 4) from None
    except RuntimeError as exc:  # the connectors' refusals: GitHub rate limit, Discourse rate limiting
        if "GitHub" in str(exc):
            raise GateError("GitHub rate limit reached.", "Set GITHUB_TOKEN to a read-only token.", 4) from None
        raise GateError("The forum is limiting requests.", "Wait a minute, then retry.", 4) from None
    except ValueError as exc:  # the connectors' "not found" and unreadable-input errors
        text = str(exc)
        if text.startswith("GitHub") and "not found" in text:
            raise GateError(
                "GitHub returned 404: the URL is wrong or the repo is private.", "DecRack reads public data only.", 4
            ) from None
        if text.startswith("Discourse topic") and "not found" in text:
            raise GateError(
                "The forum returned 404: the thread URL is wrong, or the thread is private or deleted.",
                "Check the thread URL.",
                4,
            ) from None
        raise GateError(f"Could not read this discussion: {text}", "Check the source and retry.", 4) from None


def check_content(thread: Thread) -> None:
    """Gate 4: some post still has a sentence to cite (none may be left after leak stripping)."""
    if not any(post.sentences for post in thread.posts):
        raise GateError(NOTHING_TO_ANALYZE, code=0)


def check_query(query: str | None) -> str:
    """Gate 5a: a question or file path was given."""
    value = (query or "").strip()
    if not value:
        raise GateError(EMPTY_QUERY, code=2)
    return value


def check_change_input(pr_url: str | None, paths: list[str] | None, diff: str | None) -> None:
    """Gate 5b: check-pr was given a PR URL, paths or a diff."""
    if not ((pr_url or "").strip() or paths or (diff or "").strip()):
        raise GateError(CHANGE_INPUT, code=2)


def check_records(store: Any, raw: bool = False) -> None:
    """Gate 5c: the store holds decisions (or, for a raw post search, stored threads)."""
    empty = not store.list_threads() if raw else not store.all_records()
    if empty:
        raise GateError(EMPTY_DB, code=1)
