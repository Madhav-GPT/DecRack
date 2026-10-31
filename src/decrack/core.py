"""Validated decision extraction and file-to-decision matching."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import PurePosixPath


def validate_thread(thread: object) -> dict:
    if not isinstance(thread, dict):
        raise ValueError("Discussion input must be a JSON object.")
    for key in ("id", "title", "url"):
        if not isinstance(thread.get(key), str) or not thread[key].strip():
            raise ValueError(f"Discussion field '{key}' must be a non-empty string.")
    messages = thread.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Discussion must contain at least one message.")
    seen: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each discussion message must be an object.")
        if not isinstance(message.get("id"), str) or not message["id"].strip():
            raise ValueError("Each discussion message must have a non-empty id.")
        if message["id"] in seen:
            raise ValueError(f"Duplicate discussion message id: {message['id']}")
        seen.add(message["id"])
        if not isinstance(message.get("body"), str) or not message["body"].strip():
            raise ValueError(f"Message {message['id']} must have a non-empty body.")
    return thread


def recover_decisions(thread: dict, model_response: object, *, model: str | None = None) -> dict:
    """Attach verified source references to a model's structured extraction."""
    validate_thread(thread)
    if not isinstance(model_response, dict) or not isinstance(model_response.get("decisions"), list):
        raise ValueError("Model response must contain a decisions array.")

    messages = {message["id"]: message for message in thread["messages"]}
    decisions = []
    for number, item in enumerate(model_response["decisions"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Decision {number} must be an object.")
        title = _required_text(item, "title", number)
        outcome = item.get("outcome")
        if outcome not in {"accepted", "rejected", "uncertain"}:
            raise ValueError(f"Decision {number} has an invalid outcome.")
        rationale = _required_text(item, "rationale", number)
        alternatives = _string_list(item, "alternatives", number)
        related_paths = _string_list(item, "related_paths", number)
        evidence_ids = _string_list(item, "evidence_message_ids", number)
        if not evidence_ids:
            raise ValueError(f"Decision {number} must cite at least one source message.")
        missing = [message_id for message_id in evidence_ids if message_id not in messages]
        if missing:
            raise ValueError(f"Decision {number} cites unknown message ids: {', '.join(missing)}")
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"Decision {number} confidence must be between 0 and 1.")

        stable_id = hashlib.sha256(f"{thread['id']}\0{number}\0{title}".encode()).hexdigest()[:12]
        evidence = []
        for message_id in evidence_ids:
            source = messages[message_id]
            evidence.append(
                {
                    "message_id": message_id,
                    "author": source.get("author", "unknown"),
                    "url": source.get("url") or thread["url"],
                }
            )
        decisions.append(
            {
                "id": stable_id,
                "title": title,
                "outcome": outcome,
                "rationale": rationale,
                "alternatives": alternatives,
                "related_paths": [_normalize_path(path) for path in related_paths],
                "confidence": round(float(confidence), 3),
                "source": {"discussion_id": thread["id"], "title": thread["title"], "url": thread["url"]},
                "evidence": evidence,
            }
        )
    return {"model": model, "runtime": "Ollama (local)" if model else None, "decisions": decisions}


def surface_decisions(index: object, changed_files: list[str]) -> dict:
    if not isinstance(index, dict) or not isinstance(index.get("decisions"), list):
        raise ValueError("Decision index must contain a decisions array.")
    normalized = [_normalize_path(path) for path in changed_files]
    if not normalized:
        raise ValueError("Provide at least one changed file.")
    matches = []
    for decision in index["decisions"]:
        if not isinstance(decision, dict):
            raise ValueError("Each indexed decision must be an object.")
        paths = decision.get("related_paths", [])
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ValueError("Decision related_paths must be a list of strings.")
        normalized_paths = [_normalize_path(path) for path in paths]
        hit_paths = [
            changed
            for changed in normalized
            if any(_path_matches(changed, pattern) for pattern in normalized_paths)
        ]
        if hit_paths:
            matches.append({**decision, "matched_files": hit_paths})
    return {"changed_files": normalized, "match_count": len(matches), "matches": matches}


def _path_matches(changed: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(changed, pattern)


def _normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Repository paths must be non-empty strings.")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Path must stay inside the repository: {value}")
    return str(path)


def _required_text(item: dict, key: str, number: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Decision {number} field '{key}' must be a non-empty string.")
    return value.strip()


def _string_list(item: dict, key: str, number: int) -> list[str]:
    value = item.get(key, [])
    if not isinstance(value, list) or not all(isinstance(entry, str) and entry.strip() for entry in value):
        raise ValueError(f"Decision {number} field '{key}' must be a list of non-empty strings.")
    return [entry.strip() for entry in value]
