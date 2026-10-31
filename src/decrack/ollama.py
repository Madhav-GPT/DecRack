"""Small, local-only client for Ollama's chat API."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


class OllamaError(RuntimeError):
    """Raised when the local Ollama server cannot return a response."""


def validate_local_url(base_url: str) -> str:
    """Accept only HTTP URLs that resolve to an explicit loopback hostname."""
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Ollama must use a local URL (localhost, 127.0.0.1, or ::1).")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Ollama URL must not contain credentials, query parameters, or fragments.")
    return base_url.rstrip("/")


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: float = 120.0):
        self.base_url = validate_local_url(base_url)
        self.timeout = timeout

    def extract(self, thread: dict, model: str) -> dict:
        system = (
            "Extract only engineering decisions supported by the supplied discussion. "
            "Return a JSON object with a decisions array. Each decision must have: title, "
            "outcome (accepted, rejected, or uncertain), rationale, alternatives (array of strings), "
            "related_paths (array of repository paths), evidence_message_ids (array of message IDs), "
            "and confidence (number from 0 to 1). Do not invent paths, evidence IDs, or conclusions. "
            "Use uncertain when the discussion does not establish an outcome."
        )
        user = "Discussion JSON:\n" + json.dumps(thread, ensure_ascii=False)
        body = json.dumps(
            {
                "model": model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode("utf-8")
        request = Request(
            self.base_url + "/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            opener = build_opener(ProxyHandler({}))
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise OllamaError(
                "Could not reach local Ollama. Start Ollama and confirm the selected model is available."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned invalid JSON.") from exc

        try:
            content = payload["message"]["content"]
            result = json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama response did not contain valid decision JSON.") from exc
        if not isinstance(result, dict) or not isinstance(result.get("decisions"), list):
            raise OllamaError("Ollama response must contain a decisions array.")
        return result
