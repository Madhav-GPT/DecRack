# DecRack

DecRack recovers engineering decisions from technical discussions and surfaces them when related files change. It keeps source discussion links with each decision so maintainers can check the original evidence.

## Current prototype

The prototype has two steps:

1. `recover` sends a public discussion to a local Ollama server and asks an open-weight model for structured decisions, rejected alternatives, affected paths, and message references.
2. `surface` matches saved decisions to changed files and prints the relevant records and citations.

Inference is local-only. DecRack rejects non-loopback Ollama URLs and does not call cloud inference APIs. Qwen3-4B is the provisional default candidate; it has not yet been run against this prototype, so this repository makes no open-source model scoring claim.

## Install

Requires Python 3.11 or later. The package has no Python runtime dependencies.

```bash
python -m pip install -e .
```

To use `recover`, install and start Ollama separately, then pull a compatible model such as `qwen3:4b`. Keep the model and server local. The model name can be changed with `--model` or `DECRACK_MODEL`.

## Recover decisions

Provide a JSON discussion with a stable `id`, `title`, `url`, and messages containing `id`, `author`, `body`, and an optional message `url`:

```bash
decrack recover --input discussion.json --output decisions.json --model qwen3:4b
```

The saved output retains discussion and message URLs. The extractor rejects evidence references that do not point to a message in the supplied discussion.

## Surface decisions for changed files

```bash
decrack surface --index decisions.json --changed-file src/parser/core.c
```

Pass `--changed-file` once for each changed path. DecRack reports matching decisions as JSON. It does not post comments or issues to GitHub.

To compare a local pull request branch with its base, use a Git revision range instead:

```bash
decrack surface --index decisions.json --git-range origin/main...HEAD
```

## Example

`examples/discussion.json` and `examples/decision_index.json` use a fictional parser discussion based on the organizers' sample scenario. The index is a fixture for the surfacing step; it is not claimed as model-generated output. Generate the sample output with:

```bash
decrack surface --index examples/decision_index.json --changed-file src/parser/core.c --output examples/surface_output.json
```

## Tests

```bash
python -m unittest discover -s tests -v
```
