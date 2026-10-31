# Testing runbook

This runbook is for the team laptop that runs Ollama. It covers:

1. installing everything;
2. producing the real outputs in `examples/`;
3. recording the model responses that CI replays;
4. running the same offline checks CI runs.

Run every command from the repository root. `uv run` uses the project's own environment, so there is nothing to activate.

**Contents:** [Setup](#1-one-time-setup) · [Smoke test](#2-smoke-test) · [Produce examples](#3-produce-examples) · [Record for CI](#4-record-model-responses-for-ci) · [Offline checks](#5-run-the-offline-checks) · [Before the freeze](#6-before-the-freeze) · [Timings](#7-what-to-expect) · [Troubleshooting](#8-troubleshooting)

---

## 1. One-time setup

### uv and Python

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # or: brew install uv
```

uv installs Python 3.12 for the project by itself when needed.

### Ollama and the model

1. Install Ollama from <https://ollama.com/download>, or with `brew install ollama` on macOS.
2. Start it: open the Ollama app, or run `ollama serve` in a terminal.
3. Pull the model:

```bash
ollama pull qwen2.5:1.5b    # DecRack's model, about 1 GB
ollama list                 # shows each tag and its ID (digest)
```

DecRack is built and timed on a base M4 MacBook Pro with 16 GB. Bigger open models still work: pull one and pass `--model TAG` before the command.

> **The 4K context trap.** Ollama's default context is only **4K tokens** on machines with less than 24 GiB of VRAM, which means every 16 GB laptop. Longer prompts are cut **silently**.
>
> - **DecRack's own calls are safe.** DecRack sets the context size on every request (`num_ctx`, 8,192 by default, for windows of 3,000 tokens).
> - **OpenCode's calls are not.** OpenCode reaches Ollama through an endpoint that can't set the context size per request. If you will run OpenCode on a local model, raise Ollama's default instead: quit the Ollama app, then start the server with
>
>   ```bash
>   OLLAMA_CONTEXT_LENGTH=32768 ollama serve
>   ```
>
> - **Check it.** `ollama ps` shows the context each loaded model got.

### DecRack

DecRack isn't on PyPI. Work from a clone:

```bash
git clone https://github.com/Madhav-GPT/DecRack.git
cd DecRack
uv sync                     # installs DecRack plus pytest and ruff
uv run decrack doctor
```

To put a bare `decrack` command on your PATH, run `uv tool install git+https://github.com/Madhav-GPT/DecRack`. Coding agents use the same CLI, guided by [`AGENTS.md`](../AGENTS.md) (see [OPENCODE.md](OPENCODE.md)).

`doctor` checks three things and tells you how to fix each one that fails. It ends with the two commands to tell your agent (`decrack run <URL>`, then `decrack why "<question>" --format json`):

1. that Ollama answers at `http://127.0.0.1:11434`;
2. that the configured model is pulled;
3. that `opencode` is on your PATH.


There is no config file. Settings are the global flags (`--db`, `--model`, `--ollama-host`, `--support-check`, all placed before the command), plus two environment variables: `DECRACK_DB` for the database file and `DECRACK_LLM=replay` for offline replay.

### GitHub token (only for GitHub sources)

The venue network shares one IP, and anonymous GitHub requests are capped at 60 an hour per IP, so the cap runs out fast. A token raises it to 5,000 an hour.

1. Create a fine-grained personal access token with **read-only access to public repositories** and no other permissions.
2. Export it in your shell as `GITHUB_TOKEN`. If the GitHub CLI is installed, `gh auth token` prints one you already have.

DecRack reads the token from the environment only, sends it only to the GitHub API, and never writes to GitHub. Never put the token in a file in this repo.

---

## 2. Smoke test

```bash
uv run decrack run pep:830            # 29 posts: a handful of model calls, under a minute (estimate)
uv run decrack why "exception notes"
uv run decrack why "excepthook"
uv run decrack ask pep:830 "was attaching timestamps through exception notes rejected?"
```

You should see a compact decision card for PEP 830. Each option shows its status, its status kind (`confirmed`, `inferred`, `contested` or `unresolved`) and its confidence, and the quotes carry sentence aliases such as `[p4.s2]`. Run `uv run decrack run pep:830` a second time: it should finish almost at once, because every model call is now cached in `decrack.db`.

To try a bigger open model, pass its Ollama tag with the global `--model` option, which goes before the command (`uv run decrack --model TAG run pep:830`). To turn on the optional support check, add the global `--support-check` flag, also before the command (`uv run decrack --support-check run pep:830`). Records then carry `supported`, `partial` or `unsupported` verdicts instead of `support: unchecked`, and a claim judged unsupported is downgraded from `confirmed` to `inferred`.

---

## 3. Produce examples

Everything in `examples/` must come from a real run with the real model. Never edit these files by hand, and never copy replayed test output into `examples/`.

**Evaluation runs (the main evidence).** Start with the five dev PEPs, then add the stretch PEPs and the control:

```bash
# Dev set, with the closed-book baseline
uv run decrack eval pep:830 pep:799 pep:806 pep:836 pep:822 \
  --gold eval/gold --out examples/runs --closed-book

# Full set: cached calls are free, so the dev PEPs cost nothing the second time
uv run decrack eval pep:830 pep:799 pep:806 pep:836 pep:822 pep:844 pep:842 pep:810 \
  --gold eval/gold --out examples/runs --closed-book
```

This writes one run folder per PEP, `examples/runs/pep-0830/` and so on, plus `examples/runs/eval-summary.md` and `eval-summary.json`. (`examples/runs` is also the default for `--out`.) Each folder holds:

- `thread.json`: the input exactly as ingested;
- `records.json`: what the model and the code produced;
- `scores.json`: the scores against the gold;
- `matches.json`: every predicted-to-gold pair from the deterministic fuzzy matching, for human review;
- `run.json`: the model tag, the model digest (from Ollama's `/api/show`), the Ollama version, `num_ctx` and the other settings, the prompt and schema versions, the source allowlist, timings, calls and tokens.

The five dev PEPs should take about 5–7 minutes on a base M4 with 16 GB (an estimate until measured). PEP 810 is long (464 posts), so run it last, or leave it out if time is short. The demo uses PEP 830. To include the optional support check, put the global flag before the command: `uv run decrack --support-check eval …`.

**Review the matches by hand.** For each PEP, read `matches.json`: does each predicted option really match its gold idea? Note any wrong or missed pairs in the PR that adds the runs. If you ran with `--support-check`, also spot-check a sample of the `support` verdicts in `records.json`.

**One GitHub example** (for the `check-pr` demo). Pick a merged pull request with a real design discussion in its review comments, such as 20–60 comments with at least one alternative turned down. Then run:

```bash
uv run decrack run https://github.com/OWNER/REPO/pull/NUMBER --out examples/runs/github-REPO-NUMBER
```

**The OKF bundle:**

```bash
uv run decrack export okf --out examples/okf
```

**Check them:**

```bash
uv run decrack verify examples
```

`verify` finds every folder under `examples/` that holds both `thread.json` and `records.json`, and checks every quote in every record against the posts in `thread.json`. Under `examples/runs` it also requires a `run.json` whose `mode` is `live`: replayed or scripted output is refused there, because it proves the logic, not the model. It must report no problems before anything is committed.

---

## 4. Record model responses for the tests

CI has no model. Its tests replay the responses recorded in `tests/fixtures/llm_calls.jsonl`. After the real runs, export every recorded call:

```bash
uv run decrack export calls --out tests/fixtures/llm_calls.jsonl
```

- **What a line holds:** one call's hash key, step, model, request and response.
- **How replay works:** with `DECRACK_LLM=replay`, DecRack answers each request from this file instead of Ollama.
- **Misses fail loudly:** a request that was never recorded fails with a clear "record it first" error; it never silently passes.
- **Recordings are test data only.** Replay proves the pipeline logic, not the model, so the model's evidence is always the real run folders in `examples/runs/`.

---

## 5. Run the offline checks

These are the steps of CI's one job, "DecRack checks" (`.github/workflows/ci.yml`), so a green run here should mean a green run there:

```bash
export DECRACK_LLM=replay                                        # no model from here on

uv run ruff check src tests scripts                              # lint
uv run python -m compileall -q src                               # compile
uv run pytest -q                                                 # tests
uv run decrack verify examples                                   # example evidence
uv run python scripts/compliance_check.py                        # compliance scan
uv build                                                         # build
```

Run `unset DECRACK_LLM` before going back to real runs.

**Optional: look inside the database.** Every model call, with its step, model, tokens and time, is in `llm_calls`:

```bash
sqlite3 decrack.db "SELECT step, model, ms, tokens_in, tokens_out FROM llm_calls;"
uvx datasette decrack.db          # optional browser view of every table
```

---

## 6. Before the freeze

- [ ] `examples/runs/` has a folder per PEP (each with `run.json`), plus `eval-summary.md`, and `uv run decrack verify examples` is clean.
- [ ] Every `run.json` shows the model digest and the Ollama version.
- [ ] Every `matches.json` was reviewed by hand, and any wrong pairs are noted in the PR.
- [ ] `tests/fixtures/llm_calls.jsonl` is exported, and `DECRACK_LLM=replay uv run pytest -q` passes.
- [ ] The results table in `README.md` is filled from `examples/runs/eval-summary.md`.
- [ ] `HACKATHON.md` names exactly the model tag found in `examples/runs/*/run.json` (`qwen2.5:1.5b` via Ollama). Claiming a model the code doesn't use costs points.
- [ ] Every PR's "Models the product uses" line matches that tag.
- [ ] `decrack.db` stays on the demo laptop as the precomputed demo state. It is git-ignored; don't commit it.

---

## 7. What to expect

**These are estimates until we measure them,** for `qwen2.5:1.5b` on a base M4 MacBook Pro with 16 GB, at about 6–8 seconds per model call.

- **What a compile costs.** By default it makes one map call per window of about 3,000 tokens, and nothing else touches the model.
- **The optional steps add calls.** `--support-check` adds about one call per 8 claims, and `--closed-book` adds one call per PEP.
- **The real numbers** for every run are in its `run.json` (seconds, model calls, windows, tokens) and in `llm_calls` (milliseconds and tokens per call).

| Thread | Posts | Map calls | Time |
|---|---|---|---|
| PEP 830 | 29 | about 4–6 | under a minute |
| PEP 836 | 84 | about 10–15 | 1–2 minutes |
| The 5 dev PEPs (830, 799, 806, 836, 822) | 316 | about 40–50 | about 5–7 minutes |
| PEP 810 | 464 | about 50–60 | about 6–8 minutes |

The very first call also loads the model into memory, which adds a few seconds.

---

## 8. Troubleshooting

**Reading DecRack's errors.** Every input check prints a plain error and its fix; with `--format json` it prints `{"ok": false, "error": "...", "fix": "..."}`. The exit codes are:

- 2: no source, or an empty query;
- 3: the model isn't ready;
- 4: the fetch failed;
- 1: the database is empty;
- 0: nothing to analyze.

**`doctor` says Ollama isn't reachable.**
- Start the Ollama app, or run `ollama serve`.
- Check that it answers with `curl http://127.0.0.1:11434/api/tags`.
- If Ollama runs on another machine, start it there with `OLLAMA_HOST=0.0.0.0 ollama serve` and pass `--ollama-host http://THAT-MACHINE:11434` before the command. The flag is the only way to change the host.

**"model not found".** Run `ollama pull qwen2.5:1.5b` and confirm the tag with `ollama list`. The tag must match `--model` exactly.

**Runs are slow.**
- **Close heavy apps.** The model needs the memory.
- **Don't run OpenCode's model and a `decrack run` at the same time on a 16 GB machine.** Two loaded models compete for memory. `OLLAMA_MAX_LOADED_MODELS=1` keeps only one loaded.
- **Stay on `qwen2.5:1.5b`.** Larger models are slower.
- **Leave the optional steps off.** `--support-check` adds model calls; leave it out when you only need speed.
- **Precompute.** Run the demo and eval threads well before the demo; cached calls replay instantly.
- **Re-run after a crash.** Calls that finished are cached, so the run picks up where it stopped.

**Answers look truncated, or the model ignores most of the thread.**
- Run `ollama ps` and check the context. DecRack's own requests ask for 8,192 tokens.
- If `tokens_in` in `llm_calls` is stuck at exactly 4,096 on many calls, something capped the context.

**The model's JSON fails validation.**
- The call fails with an error naming the step.
- Run the same command again: finished calls are cached, so only the failed one re-runs.
- If one thread keeps failing, try a bigger open model for that thread with `--model TAG`.

**GitHub returns 401, 403 or 404.**
- Check that `GITHUB_TOKEN` is exported in this shell.
- Check that the token hasn't expired and can read public repositories.
- A 403 or 429 with rate-limit headers means wait for the reset time (anonymous: 60 requests an hour per IP).

**discuss.python.org returns 429.** Discourse allows about 200 anonymous requests a minute per IP, and DecRack needs only one per topic. Wait a minute and run the command again.

**A test fails with "record it first".** The pipeline made a request that isn't in `tests/fixtures/llm_calls.jsonl`. This usually means a prompt or setting changed after the recordings. Re-run the affected threads with Ollama, then `uv run decrack export calls --out tests/fixtures/llm_calls.jsonl` again.

**`verify` reports a mismatch.** A run folder no longer matches its thread, for example because `records.json` was copied from another run. Regenerate that folder with `decrack eval` or `decrack run --out`. Never fix the JSON by hand.

**Citations show `source_changed`.** Someone edited the post after DecRack read it. The old text stays in `post_versions`, so the old citation still resolves, but it no longer matches the live post. Re-run the thread to compile against the current versions.

**"database is locked".** Another `decrack` command, such as a second `decrack run`, is writing. Wait for it to finish, or give one of them its own file with `--db`.

**`doctor` can't find `opencode`.** Install OpenCode (<https://opencode.ai>) and make sure the `opencode` binary is on your PATH. See [OPENCODE.md](OPENCODE.md).
