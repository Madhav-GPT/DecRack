#!/usr/bin/env python3
"""Fail the build if the repo references closed models, hosted base URLs or secrets.

DecRack's only model runtime is an open-weight model in local Ollama. This scan
keeps it that way. It checks the code, tests, scripts, docs, examples and
packaging files for:

* names of closed models and their vendors,
* the identifier ``base_url`` (including any ``*_BASE_URL`` setting),
* strings shaped like GitHub tokens or hosted-API secret keys.

Files under ``examples/`` and ``tests/fixtures/`` hold recorded third-party
discussion text, which DecRack quotes verbatim and cannot edit. A model *name*
found there is reported as a warning (``--strict`` turns it into a failure);
base URLs and secrets fail everywhere.

Usage: ``python scripts/compliance_check.py [--root DIR] [--strict]``.
Exit code 0 when clean, 1 when something must be fixed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCAN_DIRS = ("src", "tests", "scripts", "docs", "examples", ".github")
SCAN_FILES = ("pyproject.toml", "decrack.toml.example")
EXCLUDED = {
    ".github/pull_request_template.md",  # the organizers' template, kept verbatim
    "HACKATHON.md",  # the team's declaration, edited by hand in the last PR
    "scripts/compliance_check.py",  # this file
}
TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".jsonl", ".toml", ".yml", ".yaml", ".txt",
    ".cfg", ".ini", ".rst", ".sh", ".example", ".html",
}
RECORDED_DATA_PREFIXES = ("examples/", "tests/fixtures/")
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build"}

# The bracketed first letters keep each pattern from matching its own source
# line, so neither this script nor anyone grepping the repo trips over it.
MODEL_PATTERNS = [
    ("closed-model vendor", re.compile(r"[o]pen[-_]?ai(?![a-z])", re.IGNORECASE)),
    ("closed-model vendor", re.compile(r"[a]nthropic", re.IGNORECASE)),
    ("closed model", re.compile(r"(?<![a-z])[c]laude(?![a-z])", re.IGNORECASE)),
    ("closed model", re.compile(r"(?<![a-z])[c]odex(?![a-z])", re.IGNORECASE)),
    ("closed model", re.compile(r"[c]hatgpt", re.IGNORECASE)),
    ("closed model", re.compile(r"(?<![a-z])[g]pt(?![a-z])", re.IGNORECASE)),
    ("closed model", re.compile(r"(?<![a-z])[g]emini(?![a-z])", re.IGNORECASE)),
]
# The repository owner's GitHub username appears in clone URLs and badges.
ALLOWED = re.compile(r"Madhav-GPT", re.IGNORECASE)
HARD_PATTERNS = [
    ("hosted-model base URL setting", re.compile(r"[b]ase_url", re.IGNORECASE)),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9])[g]h[pousr]_[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(r"[g]ithub_pat_[A-Za-z0-9_]{20,}")),
    ("secret key", re.compile(r"(?<![A-Za-z0-9])[s]k-[A-Za-z0-9_-]{20,}")),
]


def files_to_scan(root: Path) -> list[Path]:
    """Every text file the scan covers, as paths relative to ``root``."""
    found: set[Path] = set()
    for name in SCAN_FILES:
        if (root / name).is_file():
            found.add(Path(name))
    for path in root.glob("*.md"):
        found.add(path.relative_to(root))
    for directory in SCAN_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if SKIP_PARTS.intersection(relative.parts):
                continue
            found.add(relative)
    return sorted(p for p in found if p.as_posix() not in EXCLUDED)


def scan_file(root: Path, relative: Path) -> tuple[list[str], list[str]]:
    """Return (failures, warnings) for one file."""
    failures: list[str] = []
    warnings: list[str] = []
    recorded = relative.as_posix().startswith(RECORDED_DATA_PREFIXES)
    text = (root / relative).read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in HARD_PATTERNS:
            match = pattern.search(line)
            if match:
                failures.append(f"{relative}:{number}: {label}: {match.group(0)[:12]}...")
        named_line = ALLOWED.sub("", line)
        for label, pattern in MODEL_PATTERNS:
            match = pattern.search(named_line)
            if match:
                message = f"{relative}:{number}: {label}: {match.group(0)!r}"
                (warnings if recorded else failures).append(message)
    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    parser.add_argument("--strict", action="store_true", help="treat warnings in recorded data as failures")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    files = files_to_scan(root)
    failures: list[str] = []
    warnings: list[str] = []
    for relative in files:
        file_failures, file_warnings = scan_file(root, relative)
        failures.extend(file_failures)
        warnings.extend(file_warnings)

    for message in warnings:
        print(f"warning: {message} (recorded discussion text)")
    if args.strict:
        failures.extend(warnings)
    for message in failures:
        print(f"error: {message}")

    if failures:
        print(f"compliance: FAILED, {len(failures)} problem(s) in {len(files)} file(s) scanned")
        return 1
    print(f"compliance: OK, {len(files)} file(s) scanned, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
