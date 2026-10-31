"""Settings for DecRack.

Precedence, lowest first: built-in defaults, an optional ``decrack.toml``,
the environment variables ``DECRACK_LLM`` and ``DECRACK_DB``, then CLI flags.

The model runtime is always a local Ollama server. Its address is the
constant below and can only be changed with the ``--ollama-host`` CLI flag.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:4b"
ALTERNATIVE_MODELS = ("gemma4:e4b", "qwen3.5:9b")
DEFAULT_DB = "decrack.db"
DEFAULT_REPLAY_FILE = "tests/fixtures/llm_calls.jsonl"
DEFAULT_CONFIG_FILE = "decrack.toml"

# Keys a decrack.toml may set. The Ollama host is deliberately not one of them.
TOML_KEYS = (
    "db_path",
    "model",
    "num_ctx",
    "window_max_tokens",
    "window_overlap_tokens",
    "merge_with_llm",
    "refine_reasons",
    "reasons_max_tokens",
    "support_check",
    "support_batch_size",
    "request_timeout",
    "replay_file",
    "budget_tokens",
)


class Settings(BaseModel):
    db_path: str = DEFAULT_DB
    model: str = DEFAULT_MODEL
    ollama_host: str = DEFAULT_OLLAMA_HOST
    llm_mode: Literal["ollama", "replay"] = "ollama"
    replay_file: str = DEFAULT_REPLAY_FILE
    num_ctx: int = 32768  # set explicitly: Ollama truncates to 4K on small GPUs otherwise
    window_max_tokens: int = 6000  # per MAP window; tokens ~ chars / 4
    window_overlap_tokens: int = 800  # rounded to whole posts, at least one post
    merge_with_llm: bool = True  # one extra "merge" call per thread
    refine_reasons: bool = True  # "refine_reasons" calls for decided options
    reasons_max_tokens: int = 12000
    support_check: bool = True  # batched "support" calls; off means every claim stays "unchecked"
    support_batch_size: int = 8
    request_timeout: float = 600.0
    eval_mode: bool = False  # turns on the PEP leak guard
    budget_tokens: int = 10000  # size cap for MCP and CLI output


def load_settings(
    db: str | None = None,
    model: str | None = None,
    ollama_host: str | None = None,
    config_path: str | Path | None = None,
) -> Settings:
    """Build Settings from defaults, decrack.toml, environment and CLI flags."""
    values: dict[str, object] = {}

    path = Path(config_path) if config_path else Path(DEFAULT_CONFIG_FILE)
    if path.is_file():
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        section = data.get("decrack", data)
        for key in TOML_KEYS:
            if key in section:
                values[key] = section[key]

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

    return Settings(**values)
