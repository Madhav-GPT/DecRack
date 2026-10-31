"""Settings for DecRack.

Precedence, lowest first: built-in defaults, the environment variables
``DECRACK_LLM`` (``replay`` makes CI answer from recorded model calls) and
``DECRACK_DB``, then CLI flags. There is no settings file.

The model runtime is always a local Ollama server. Its address is the
constant below and can only be changed with the ``--ollama-host`` CLI flag.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:1.5b"
DEFAULT_DB = "decrack.db"
DEFAULT_REPLAY_FILE = "tests/fixtures/llm_calls.jsonl"


class Settings(BaseModel):
    db_path: str = DEFAULT_DB
    model: str = DEFAULT_MODEL
    ollama_host: str = DEFAULT_OLLAMA_HOST
    llm_mode: Literal["ollama", "replay"] = "ollama"
    replay_file: str = DEFAULT_REPLAY_FILE
    num_ctx: int = 8192  # set explicitly: Ollama's own default is smaller and silently truncates
    window_max_tokens: int = 3000  # per MAP window; tokens ~ chars / 4
    window_overlap_tokens: int = 300  # rounded to whole posts, at least one post
    support_check: bool = False  # optional batched "support" calls (--support-check); off: claims stay "unchecked"
    support_batch_size: int = 8
    request_timeout: float = 600.0
    eval_mode: bool = False  # turns on the PEP leak guard
    budget_tokens: int = 10000  # size cap for CLI output (why, show, check-pr)


def load_settings(
    db: str | None = None,
    model: str | None = None,
    ollama_host: str | None = None,
    support_check: bool | None = None,
) -> Settings:
    """Build Settings from defaults, the environment and CLI flags."""
    values: dict[str, object] = {}

    llm_mode = os.environ.get("DECRACK_LLM", "").strip().lower()
    if llm_mode in ("ollama", "replay"):
        values["llm_mode"] = llm_mode
    env_db = os.environ.get("DECRACK_DB", "").strip()
    if env_db:
        values["db_path"] = env_db

    if db:
        values["db_path"] = db
    if model:
        values["model"] = model
    if ollama_host:
        values["ollama_host"] = ollama_host.rstrip("/")
    if support_check is not None:
        values["support_check"] = support_check

    return Settings(**values)
