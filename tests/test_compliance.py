"""Tests for scripts/compliance_check.py.

Forbidden words are assembled at runtime ("open" + "ai") so this file never
contains them literally and the scan of tests/ stays clean.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "compliance_check.py"


def run_scan(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *extra],
        capture_output=True,
        text=True,
    )


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_clean_tree_passes(tmp_path):
    write(tmp_path, "src/decrack/llm.py", 'HOST = "http://127.0.0.1:11434"\nMODEL = "qwen3.5:4b"\n')
    write(tmp_path, "README.md", "Runs gemma4:e4b in local Ollama.\n")
    result = run_scan(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "compliance: OK" in result.stdout


def test_vendor_name_in_code_fails(tmp_path):
    write(tmp_path, "src/decrack/llm.py", "import " + "open" + "ai\n")
    result = run_scan(tmp_path)
    assert result.returncode == 1
    assert "src/decrack/llm.py:1" in result.stdout


def test_hosted_address_setting_fails(tmp_path):
    write(tmp_path, "docs/setup.md", "Set OLLAMA_" + "BASE" + "_URL to your server.\n")
    result = run_scan(tmp_path)
    assert result.returncode == 1
    assert "base URL" in result.stdout


def test_token_shaped_string_fails(tmp_path):
    write(tmp_path, "tests/test_x.py", 'TOKEN = "' + "gh" + "p_" + "a1" * 18 + '"\n')
    result = run_scan(tmp_path)
    assert result.returncode == 1
    assert "GitHub token" in result.stdout


def test_recorded_discussion_text_only_warns(tmp_path):
    write(tmp_path, "examples/pep-1/thread.json", '{"text": "I asked ' + "Chat" + "G" + 'PT about it."}\n')
    result = run_scan(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "warning:" in result.stdout
    strict = run_scan(tmp_path, "--strict")
    assert strict.returncode == 1


def test_repository_owner_name_is_allowed(tmp_path):
    write(tmp_path, "README.md", "git clone https://github.com/Madhav-GPT/DecRack.git\n")
    result = run_scan(tmp_path)
    assert result.returncode == 0, result.stdout


def test_excluded_files_are_not_scanned(tmp_path):
    write(tmp_path, ".github/pull_request_template.md", "Example: " + "Cl" + "aude Code, or none.\n")
    write(tmp_path, "HACKATHON.md", "Assistants: " + "Co" + "dex.\n")
    result = run_scan(tmp_path)
    assert result.returncode == 0, result.stdout
