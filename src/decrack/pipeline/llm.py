"""Model access: one small client for Ollama's native ``/api/chat``, plus replay and scripted stand-ins.

Every structured call goes through ``complete_json(step, messages, schema, key_extra=...)``.
The request (model, step, messages, inlined schema, options, think and the
optional ``extra`` dict) is hashed into a cache key: ``OllamaLLM`` stores each
answer under it, ``ReplayLLM`` answers from a JSONL export of those answers,
and ``ScriptedLLM`` answers from queues in tests. ``extra`` holds what an
answer depends on beyond the messages, such as the model digest and, for a MAP
call, the window's post versions and the key of the window before it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from decrack.config import DEFAULT_MODEL, DEFAULT_OLLAMA_HOST, Settings

Schema = type[BaseModel] | dict
ScriptedResponse = dict | Callable[[list[dict]], dict]

RECORD_HINT = "Record it first: run DecRack with Ollama, then `decrack export calls --out <path>`."
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
THINK_END_RE = re.compile(r"</think>", re.IGNORECASE)
INFO_TIMEOUT = 10.0  # seconds for the small /api/tags and /api/version requests
LOOSE_FIELDS = ("step", "messages", "schema", "think")


class LLMError(Exception):
    """Base class for model errors."""


class ReplayMissError(LLMError):
    """No recorded response matches the request."""


class LLMUnavailableError(LLMError):
    """Ollama is unreachable, the model is not installed, or Ollama answered with an HTTP error."""


class LLMOutputError(LLMError):
    """The model's answer was not valid JSON for the schema, even after one retry."""


class LLM(Protocol):
    model: str
    mode: str  # "live", "replay" or "scripted"; becomes RunInfo.mode
    calls: int
    cache_hits: int
    tokens_in: int
    tokens_out: int

    def complete_json(
        self,
        step: str,
        messages: list[dict],
        schema: type[BaseModel] | dict,
        think: bool = False,
        model: str | None = None,
        key_extra: dict | None = None,
    ) -> dict: ...


def inline_schema(schema: dict) -> dict:
    """Replace every ``$ref`` with its ``$defs`` entry and drop ``$defs``: small models handle flat schemas better."""
    definitions = schema.get("$defs", {})

    def resolve(node: Any, active: tuple[str, ...]) -> Any:
        if isinstance(node, list):
            return [resolve(item, active) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = str(node["$ref"]).rsplit("/", 1)[-1]
            if name in active:
                raise ValueError(f"schema reference {name} is recursive and cannot be inlined")
            if name not in definitions:
                raise ValueError(f"unknown schema reference {node['$ref']}")
            target = resolve(definitions[name], active + (name,))
            siblings = {key: resolve(value, active) for key, value in node.items() if key != "$ref"}
            return {**target, **siblings}
        return {key: resolve(value, active) for key, value in node.items() if key != "$defs"}

    return resolve(schema, ())


def schema_dict(schema: Schema) -> dict:
    """The inlined JSON schema for a Pydantic model class or a JSON-schema dict."""
    if isinstance(schema, dict):
        return inline_schema(schema)
    return inline_schema(schema.model_json_schema())


def build_request(
    model: str,
    step: str,
    messages: list[dict],
    schema: Schema,
    options: dict,
    think: bool,
    extra: dict | None = None,
) -> dict:
    """Everything that determines a model answer; its hash is the cache key.

    ``extra`` (the caller's ``key_extra``) is added under "extra" only when given,
    so a request without it keeps the same key as before.
    """
    request = {
        "model": model,
        "step": step,
        "messages": messages,
        "schema": schema_dict(schema),
        "options": options,
        "think": think,
    }
    if extra is not None:
        request["extra"] = extra
    return request


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def call_key(request: dict) -> str:
    """sha256 hex of the request's canonical JSON."""
    return hashlib.sha256(canonical_json(request).encode("utf-8")).hexdigest()


def loose_key(request: dict) -> str:
    """Key of step, messages, schema, think and ``extra`` without its "digest" entry.

    Model tag, options and model digest are left out, so a recording made with
    another model tag, num_ctx or Ollama build still replays. The rest of
    ``extra`` stays: a MAP call over other post versions, other known
    alternatives or another chain still misses.
    """
    loose = {name: request.get(name) for name in LOOSE_FIELDS}
    extra = request.get("extra")
    if isinstance(extra, dict):
        loose["extra"] = {name: value for name, value in extra.items() if name != "digest"}
    return call_key(loose)


def strip_think(text: str) -> str:
    """Remove ``<think>...</think>`` blocks, and anything before a ``</think>`` whose opening tag is missing."""
    text = THINK_RE.sub("", text)
    return THINK_END_RE.split(text)[-1].strip()


def parse_json(text: str) -> Any:
    """Parse a reply; fall back to its outermost ``{...}`` when prose or code fences surround the JSON."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def conform(data: Any, schema: Schema) -> dict:
    """Validate parsed output against the schema class and return its plain dict (ValueError if it does not fit)."""
    if isinstance(schema, dict):
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data
    return schema.model_validate(data).model_dump(mode="json")


def short_error(error: Exception, limit: int = 800) -> str:
    return " ".join(str(error).split())[:limit]


def _string(data: Any, name: str) -> str:
    """``data[name]`` when ``data`` is a dict and that value a string, else ""."""
    value = data.get(name) if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


class OllamaLLM:
    """Calls a local Ollama server through its native ``/api/chat`` endpoint, one request at a time."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_OLLAMA_HOST,
        num_ctx: int = 32768,
        store: Any = None,
        client: httpx.Client | None = None,
        timeout: float = 600.0,
    ) -> None:
        self.model = model
        self.mode = "live"
        self.host = host.rstrip("/")
        self.num_ctx = num_ctx
        self.store = store
        self.timeout = timeout
        self._owns_client = client is None
        self.client = client if client is not None else httpx.Client(timeout=timeout)
        self.calls = 0
        self.cache_hits = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def close(self) -> None:
        """Close the HTTP client if this object created it."""
        if self._owns_client:
            self.client.close()

    def complete_json(
        self,
        step: str,
        messages: list[dict],
        schema: type[BaseModel] | dict,
        think: bool = False,
        model: str | None = None,
        key_extra: dict | None = None,
    ) -> dict:
        """Answer from the store when this exact request was made before, else ask Ollama.

        ``key_extra`` goes into the cache key only; Ollama never sees it.
        """
        self.calls += 1
        model_name = model or self.model
        options = {"num_ctx": self.num_ctx, "temperature": 0}
        request = build_request(model_name, step, messages, schema, options, think, key_extra)
        key = call_key(request)
        if self.store is not None:
            cached = self.store.get_llm_call(key)
            if cached is not None:
                self.cache_hits += 1
                return cached

        started = time.monotonic()
        conversation = list(messages)
        tokens_in = tokens_out = 0
        for attempt in (1, 2):
            body = self._chat(model_name, conversation, request["schema"], think, options)
            used_in, used_out = int(body.get("prompt_eval_count") or 0), int(body.get("eval_count") or 0)
            tokens_in, tokens_out = tokens_in + used_in, tokens_out + used_out
            self.tokens_in, self.tokens_out = self.tokens_in + used_in, self.tokens_out + used_out
            reply = strip_think(str((body.get("message") or {}).get("content") or ""))
            try:
                result = conform(parse_json(reply), schema)
                break
            except (ValueError, ValidationError) as exc:
                problem = short_error(exc)
                if attempt == 2:
                    raise LLMOutputError(
                        f"Step '{step}': {model_name} gave output that does not match the schema, "
                        f"also after one retry: {problem}"
                    ) from exc
                # One retry with the error, which small models usually fix (re-prompting on bad output).
                conversation = conversation + [
                    {"role": "assistant", "content": reply},
                    {
                        "role": "user",
                        "content": f"Your reply was not valid: {problem}\n"
                        "Answer again with only a JSON object that matches the schema.",
                    },
                ]

        ms = int((time.monotonic() - started) * 1000)
        if self.store is not None:
            self.store.put_llm_call(
                key, step, model_name, request, result, ms=ms, tokens_in=tokens_in, tokens_out=tokens_out
            )
        return result

    def runtime_info(self) -> dict[str, str]:
        """``{"model_digest", "ollama_version"}`` from ``GET /api/tags`` and ``GET /api/version``.

        The digest is the one listed for the configured model (matched on ``name``
        or ``model``; a name without a tag means ``<name>:latest``). Each value is
        "" when its request fails or the answer lacks it.
        """
        wanted = {self.model} if ":" in self.model else {self.model, f"{self.model}:latest"}
        tags = self._get_json("/api/tags")
        models = tags.get("models") if isinstance(tags, dict) else None
        listed = [item for item in models if isinstance(item, dict)] if isinstance(models, list) else []
        match = next((item for item in listed if item.get("name") in wanted or item.get("model") in wanted), None)
        return {
            "model_digest": _string(match, "digest"),
            "ollama_version": _string(self._get_json("/api/version"), "version"),
        }

    def _get_json(self, path: str) -> Any:
        """``GET`` an Ollama endpoint and parse its JSON; None when anything fails."""
        try:
            response = self.client.get(f"{self.host}{path}", timeout=INFO_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            return None

    def _chat(self, model: str, messages: list[dict], schema: dict, think: bool, options: dict) -> dict:
        """One non-streaming ``/api/chat`` request with the schema as ``format``."""
        url = f"{self.host}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "think": think,
            "options": options,
        }
        try:
            response = self.client.post(url, json=payload, timeout=self.timeout)
            if response.status_code == 400 and "think" in response.text.lower():
                # Older Ollama versions and some models refuse the think flag; ask again without it.
                payload.pop("think")
                response = self.client.post(url, json=payload, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"Ollama at {self.host} did not answer within {self.timeout:g} seconds. "
                "Try a smaller model or raise request_timeout."
            ) from exc
        except httpx.TransportError as exc:
            raise LLMUnavailableError(
                f"Cannot reach Ollama at {self.host} ({exc}). Start it with `ollama serve`, "
                f"then install the model with `ollama pull {model}`."
            ) from exc

        if response.status_code == 404 or (response.status_code >= 400 and "not found" in response.text.lower()):
            raise LLMUnavailableError(
                f"Model '{model}' is not available in Ollama at {self.host}. Install it with `ollama pull {model}`."
            )
        if response.status_code >= 400:
            raise LLMUnavailableError(
                f"Ollama at {self.host} answered HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMUnavailableError(f"Ollama at {self.host} sent a response that is not JSON.") from exc
        if not isinstance(body, dict):
            raise LLMUnavailableError(f"Ollama at {self.host} sent an unexpected response.")
        return body


class ReplayLLM:
    """Answers from a JSONL file written by ``Store.export_llm_calls``; never calls a model.

    Lookup is by the exact call key first, then by ``loose_key``, which ignores
    the model tag, options and model digest, so a recording made with another
    num_ctx or Ollama build still replays. Every answered call counts as a cache hit.
    """

    def __init__(self, path: str | Path, model: str = DEFAULT_MODEL, num_ctx: int = 32768) -> None:
        self.path = Path(path)
        self.model = model
        self.mode = "replay"
        self.num_ctx = num_ctx
        self.calls = 0
        self.cache_hits = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.found = self.path.is_file()
        self.by_key: dict[str, Any] = {}
        self.by_loose_key: dict[str, Any] = {}
        if self.found:
            with self.path.open(encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        self.by_key[row["key"]] = row["response"]
                        self.by_loose_key[loose_key(row["request"])] = row["response"]
                    except (ValueError, KeyError, TypeError) as exc:
                        raise LLMError(f"{self.path}, line {number}: not a recorded call ({exc})") from exc

    def complete_json(
        self,
        step: str,
        messages: list[dict],
        schema: type[BaseModel] | dict,
        think: bool = False,
        model: str | None = None,
        key_extra: dict | None = None,
    ) -> dict:
        self.calls += 1
        if not self.found:
            raise ReplayMissError(f"Replay file {self.path} does not exist. {RECORD_HINT}")
        options = {"num_ctx": self.num_ctx, "temperature": 0}
        request = build_request(model or self.model, step, messages, schema, options, think, key_extra)
        key = call_key(request)
        response = self.by_key.get(key)
        if response is None:
            response = self.by_loose_key.get(loose_key(request))
        if response is None:
            raise ReplayMissError(f"No recorded response for step '{step}' (key {key}) in {self.path}. {RECORD_HINT}")
        self.cache_hits += 1
        try:
            return conform(copy.deepcopy(response), schema)
        except (ValueError, ValidationError) as exc:
            raise LLMOutputError(
                f"The recorded response for step '{step}' does not match the schema: {short_error(exc)}"
            ) from exc


class ScriptedLLM:
    """Test stand-in that answers each step from a queue.

    A queue holds dicts and callables ``fn(messages) -> dict``. A dict answers
    one call; a callable at the head of the queue stays there and answers every
    later call for its step. ``requests`` keeps ``(step, messages)`` of every
    call and ``key_extras`` its ``key_extra``, in the same order.
    """

    def __init__(
        self,
        responses: dict[str, list[dict] | Callable[[list[dict]], dict]] | None = None,
        model: str = "scripted",
    ) -> None:
        self.model = model
        self.mode = "scripted"
        self.calls = 0
        self.cache_hits = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.requests: list[tuple[str, list[dict]]] = []
        self.key_extras: list[dict | None] = []
        self.queues: dict[str, list[ScriptedResponse]] = {}
        for step, value in (responses or {}).items():
            for response in ([value] if callable(value) else value):
                self.add(step, response)

    def add(self, step: str, response: ScriptedResponse) -> None:
        self.queues.setdefault(step, []).append(response)

    def complete_json(
        self,
        step: str,
        messages: list[dict],
        schema: type[BaseModel] | dict,
        think: bool = False,
        model: str | None = None,
        key_extra: dict | None = None,
    ) -> dict:
        self.calls += 1
        self.requests.append((step, messages))
        self.key_extras.append(key_extra)
        queue = self.queues.get(step)
        if not queue:
            raise LLMError(f"ScriptedLLM has no response left for step '{step}'.")
        head = queue[0]
        data = head(messages) if callable(head) else queue.pop(0)
        try:
            return conform(copy.deepcopy(data), schema)
        except (ValueError, ValidationError) as exc:
            raise LLMOutputError(
                f"The scripted response for step '{step}' does not match the schema: {short_error(exc)}"
            ) from exc


def make_llm(settings: Settings, store: Any = None) -> LLM:
    """ReplayLLM when ``settings.llm_mode == "replay"``, else OllamaLLM (cached in ``store`` when given)."""
    if settings.llm_mode == "replay":
        return ReplayLLM(settings.replay_file, model=settings.model, num_ctx=settings.num_ctx)
    return OllamaLLM(
        model=settings.model,
        host=settings.ollama_host,
        num_ctx=settings.num_ctx,
        store=store,
        timeout=settings.request_timeout,
    )
