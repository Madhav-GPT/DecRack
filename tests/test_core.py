import unittest
from unittest.mock import patch
import json
from unittest.mock import Mock

from decrack.core import recover_decisions, surface_decisions
from decrack.cli import _changed_files_from_git
from decrack.ollama import OllamaClient, validate_local_url


THREAD = {
    "id": "issue-1832",
    "title": "Keep the C parser",
    "url": "https://example.invalid/project/issues/1832",
    "messages": [
        {
            "id": "m1",
            "author": "maintainer",
            "body": "The Rust rewrite was rejected because it ran twice as slowly on large files.",
            "url": "https://example.invalid/project/issues/1832#issuecomment-1",
        }
    ],
}

MODEL_RESPONSE = {
    "decisions": [
        {
            "title": "Keep the C parser for large files",
            "outcome": "accepted",
            "rationale": "The Rust rewrite was measured at twice the runtime on large files.",
            "alternatives": ["Rewrite the parser in Rust"],
            "related_paths": ["src/parser/core.c"],
            "evidence_message_ids": ["m1"],
            "confidence": 0.91,
        }
    ]
}


class DecisionCoreTests(unittest.TestCase):
    def test_recovery_keeps_traceable_message_reference(self):
        result = recover_decisions(THREAD, MODEL_RESPONSE)
        decision = result["decisions"][0]
        self.assertEqual(decision["outcome"], "accepted")
        self.assertEqual(decision["evidence"][0]["url"], THREAD["messages"][0]["url"])
        self.assertEqual(decision["related_paths"], ["src/parser/core.c"])

    def test_recovery_rejects_unknown_evidence_message(self):
        response = {"decisions": [{**MODEL_RESPONSE["decisions"][0], "evidence_message_ids": ["missing"]}]}
        with self.assertRaisesRegex(ValueError, "unknown message ids"):
            recover_decisions(THREAD, response)

    def test_surface_matches_related_file_and_keeps_source(self):
        index = recover_decisions(THREAD, MODEL_RESPONSE)
        result = surface_decisions(index, ["src/parser/core.c", "README.md"])
        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["matches"][0]["matched_files"], ["src/parser/core.c"])
        self.assertEqual(result["matches"][0]["source"]["url"], THREAD["url"])

    def test_surface_supports_glob_paths(self):
        index = recover_decisions(THREAD, MODEL_RESPONSE)
        index["decisions"][0]["related_paths"] = ["src/parser/*.c"]
        result = surface_decisions(index, ["src/parser/core.c"])
        self.assertEqual(result["match_count"], 1)

    def test_surface_rejects_paths_outside_repository(self):
        index = recover_decisions(THREAD, MODEL_RESPONSE)
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            surface_decisions(index, ["../secrets.txt"])

    def test_ollama_url_must_be_loopback(self):
        self.assertEqual(validate_local_url("http://localhost:11434/"), "http://localhost:11434")
        with self.assertRaisesRegex(ValueError, "local URL"):
            validate_local_url("https://example.com")

    def test_ollama_client_sends_structured_request_to_local_endpoint(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"message": {"content": json.dumps(MODEL_RESPONSE)}}).encode()

        class Opener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return Response()

        opener = Opener()
        with patch("decrack.ollama.build_opener", return_value=opener):
            result = OllamaClient().extract(THREAD, "qwen3:4b")
        self.assertEqual(result, MODEL_RESPONSE)
        self.assertEqual(opener.request.full_url, "http://127.0.0.1:11434/api/chat")
        body = json.loads(opener.request.data)
        self.assertEqual(body["model"], "qwen3:4b")
        self.assertEqual(body["format"], "json")

    def test_git_range_reads_changed_paths_without_shell(self):
        result = Mock(stdout=b"src/parser/core.c\0README.md\0")
        with patch("decrack.cli.subprocess.run", return_value=result) as run:
            paths = _changed_files_from_git("origin/main...HEAD")
        self.assertEqual(paths, ["src/parser/core.c", "README.md"])
        self.assertEqual(run.call_args.args[0], ["git", "diff", "--name-only", "-z", "origin/main...HEAD"])


if __name__ == "__main__":
    unittest.main()
