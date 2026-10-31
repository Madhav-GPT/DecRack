"""MAP step: one model call per window; the gate checks what comes back.

Each call's ``key_extra`` names what its answer depends on beyond the
messages: the model digest, the prompt and schema versions, the window's
``[post_id, version, sha256, first, last]`` parts, the known alternatives and
``chain``, the key of the previous window's MAP call. An appended reply
therefore re-runs only the last window, while an edit early in the thread
changes that window's key and, through ``chain``, every key after it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from decrack.models import SCHEMA_VERSION, Candidate, MapOutput, Thread
from decrack.pipeline.llm import LLM, LLMOutputError, loose_key, schema_dict
from decrack.pipeline.prompts import PROMPT_VERSION, map_messages
from decrack.pipeline.windows import Window, part_ref

# Accepts "A3", "a3", "[A3]" and "A3: name"; anything else means a new alternative.
ALT_REF_RE = re.compile(r"\W*a(\d+)\b", re.IGNORECASE)


def normalize_alt_ref(value: str) -> str:
    """``"a3"`` -> ``"A3"``; anything that is not ``A<digits>`` -> ``"new"``."""
    match = ALT_REF_RE.match(value or "")
    return f"A{int(match.group(1))}" if match else "new"


def map_key_extra(window: Window, known: list[tuple[str, str, str]], chain: str = "", digest: str = "") -> dict:
    """The ``key_extra`` of one MAP call (see the module docstring)."""
    return {
        "digest": digest,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "window": [part_ref(part) for part in window.parts],
        "known": [[key, title, summary] for key, title, summary in known],
        "chain": chain,
    }


def map_request_key(messages: list[dict], key_extra: dict) -> str:
    """The key of one MAP call without model tag, options and digest: ``llm.loose_key`` of its request.

    It becomes the next window's ``chain``. Leaving the model tag, options and
    digest out keeps the chain the same when a recording is replayed with
    another model tag, num_ctx or Ollama build; each call's own cache key still
    holds them.
    """
    request = {
        "step": "map",
        "messages": messages,
        "schema": schema_dict(MapOutput),
        "think": False,
        "extra": key_extra,
    }
    return loose_key(request)


@dataclass
class MapRequest:
    """One prepared MAP call: the window, its messages and its ``key_extra``."""

    window: Window
    messages: list[dict]
    key_extra: dict

    @property
    def key(self) -> str:
        """``map_request_key`` of this call: the ``chain`` of the next window."""
        return map_request_key(self.messages, self.key_extra)


def prepare_map(
    thread: Thread, window: Window, known: list[tuple[str, str, str]], chain: str = "", digest: str = ""
) -> MapRequest:
    """Messages and ``key_extra`` for the MAP call of ``window``, given the alternatives known so far."""
    return MapRequest(
        window=window,
        messages=map_messages(thread, known, window.parts),
        key_extra=map_key_extra(window, known, chain=chain, digest=digest),
    )


def map_window(llm: LLM, request: MapRequest) -> list[Candidate]:
    """Ask the model to label one window; alt_refs are normalised, cites are left to the gate."""
    data = llm.complete_json("map", request.messages, MapOutput, think=False, key_extra=request.key_extra)
    try:
        items = MapOutput.model_validate(data).items
    except ValidationError as exc:
        raise LLMOutputError(
            f"MAP output for window {request.window.index + 1} does not match the schema: {exc}"
        ) from exc
    return [item.model_copy(update={"alt_ref": normalize_alt_ref(item.alt_ref)}) for item in items]
