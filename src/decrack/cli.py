"""Command-line interface for local decision recovery and surfacing."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .core import recover_decisions, surface_decisions, validate_thread
from .ollama import OllamaClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decrack", description="Recover and surface traceable engineering decisions.")
    commands = parser.add_subparsers(dest="command", required=True)

    recover = commands.add_parser("recover", help="extract decisions with a local Ollama model")
    recover.add_argument("--input", required=True, type=Path, help="discussion JSON file")
    recover.add_argument("--output", required=True, type=Path, help="path for the decision index JSON")
    recover.add_argument("--model", default=os.getenv("DECRACK_MODEL", "qwen3:4b"))
    recover.add_argument("--ollama-url", default=os.getenv("DECRACK_OLLAMA_URL", "http://127.0.0.1:11434"))

    surface = commands.add_parser("surface", help="find saved decisions connected to changed files")
    surface.add_argument("--index", required=True, type=Path, help="saved decision index JSON")
    changed = surface.add_mutually_exclusive_group(required=True)
    changed.add_argument("--changed-file", action="append", help="changed repository path; repeat as needed")
    changed.add_argument("--git-range", help="Git revision range, such as origin/main...HEAD")
    surface.add_argument("--output", type=Path, help="optional JSON output file (also prints to stdout)")
    return parser


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _changed_files_from_git(revision_range: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "-z", revision_range],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Could not read changed files from Git range '{revision_range}'.") from exc
    return [path.decode("utf-8", errors="replace") for path in result.stdout.split(b"\0") if path]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "recover":
            thread = validate_thread(_read_json(args.input))
            model_response = OllamaClient(args.ollama_url).extract(thread, args.model)
            result = recover_decisions(thread, model_response, model=args.model)
            _write_json(args.output, result)
            print(f"Recovered {len(result['decisions'])} decisions to {args.output} using local model {args.model}.")
            return 0

        changed_files = args.changed_file or _changed_files_from_git(args.git_range)
        result = surface_decisions(_read_json(args.index), changed_files)
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        sys.stdout.write(output)
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"decrack: {exc}", file=sys.stderr)
        return 2
