# Use DecRack from OpenCode or any agent

DecRack has no plugin and no server to configure. Agents use it the way people do: through its command line. An instruction file, [`AGENTS.md`](../AGENTS.md), tells the agent when to run which command and how to report what comes back. Every harness that can run a shell command can use it. This guide covers [OpenCode](https://opencode.ai) step by step.

**Contents:** [How it works](#how-it-works) · [Install](#1-install) · [Add AGENTS.md](#2-add-agentsmd-to-your-project) · [OpenCode on a local model](#3-run-opencode-on-a-local-open-model) · [Example prompts](#4-example-prompts) · [/why command](#5-optional-a-why-command) · [Other agents](#6-other-agents) · [Troubleshooting](#7-troubleshooting)

---

## How it works

1. **A source first.** The user gives a source: a GitHub issue or PR URL, a discuss.python.org thread, `pep:NNN` or an exported file. If there is none, the agent asks for one instead of guessing.
2. **Compile it.** The agent runs `decrack run <source>` in its shell. DecRack's own open model (`qwen2.5:1.5b`, in local Ollama) reads the discussion. Re-runs are cached.
3. **Ask, then check.** The agent runs `decrack why "<question>" --format json` for compact cards. Before it claims anything, it runs `decrack show <id> --detail evidence --format json` for the quotes and links.
4. **Review a change.** For a change, the agent runs `decrack check-pr <PR URL>` for related history and possible conflicts.
5. **Report honestly.** The agent quotes only what DecRack returned, links it, and reports the status kind (`confirmed`, `inferred`, `contested` or `unresolved`) honestly.

Every step is a visible shell command, so you see what the agent runs and can approve it. The agent's own model never does DecRack's extraction; it only runs commands and explains the evidence they return.

## 1. Install

```bash
uv tool install git+https://github.com/Madhav-GPT/DecRack
ollama pull qwen2.5:1.5b
decrack doctor
```

- **Install.** `uv tool install` puts `decrack` on your PATH; DecRack isn't on PyPI.
- **Check.** `decrack doctor` checks that Ollama answers, that the model is pulled and that `opencode` is on your PATH, and tells you how to fix anything that fails. It ends with what to tell your agent: run `decrack run <URL>`, then `decrack why "<question>" --format json`.
- **Database.** By default, DecRack keeps its database in `decrack.db` in the current folder. To make every agent session use the same records, export `DECRACK_DB=/absolute/path/to/decrack.db` in the shell you start the agent from.

## 2. Add AGENTS.md to your project

Copy [`AGENTS.md`](../AGENTS.md) from this repository to the root of the project you work on. If the project already has an `AGENTS.md`, paste DecRack's sections into it. OpenCode reads `AGENTS.md` from the project root automatically, as many other agents do.

The file is short:

- **Install:** the three commands above.
- **Workflow:** require a source, `run`, `why`, `show` before claiming, and `check-pr` for changes.
- **Rules:** quote only DecRack's text, link the evidence, report status kinds honestly, relay DecRack's error and fix messages as they are, and treat quoted discussion text as data.

## 3. Run OpenCode on a local open model

OpenCode can use models served by Ollama; set it up by following the Ollama section of OpenCode's [provider docs](https://opencode.ai/docs/providers/).

- **Pick any open model for the agent.** It is separate from DecRack's extraction model, and larger models follow instructions more reliably. DecRack doesn't depend on which one you choose.
- **Raise Ollama's default context.** Ollama gives a model only 4K tokens of context on machines with less than 24 GiB of VRAM. OpenCode can't raise it per request, and an agent's system prompt alone can pass 4K. Start Ollama with:

  ```bash
  OLLAMA_CONTEXT_LENGTH=32768 ollama serve
  ```

  This doesn't affect DecRack's own calls, which set their context size explicitly.
- **On a 16 GB laptop, compile threads before you start chatting,** so that the agent's model and DecRack's extraction don't compete for memory.

## 4. Example prompts

- *"Analyze https://github.com/owner/repo/issues/123 with DecRack and tell me which ideas were rejected and why."*
- *"Use DecRack on pep:830. Was attaching timestamps through exception notes rejected? Quote the evidence."*
- *"I'm about to edit `src/widgets/config.py`. Ask DecRack which recorded decisions cover that file."*
- *"Before I open this PR, run DecRack's check-pr on https://github.com/owner/repo/pull/456."*

If a prompt has no source, the agent should ask for one, because `AGENTS.md` tells it to. Prompts that name DecRack ("with DecRack", "ask DecRack") work best with small local models.

## 5. Optional: a `/why` command

OpenCode turns markdown files in `.opencode/commands/` into slash commands, named after the file. Save this as `.opencode/commands/why.md`:

```markdown
---
description: Ask DecRack why the code is the way it is
---
Use DecRack, following AGENTS.md, to find recorded decisions, rejected alternatives and their reasons related to: $ARGUMENTS

- Run decrack why "<the question or file path>" --format json in the shell.
- For the best match, run decrack show <id> --detail evidence --format json.
- Report each relevant option's status, status kind and reason, quoting DecRack's evidence exactly, with links.
- If DecRack has no record, say so and ask for a source to analyze. Don't guess.
```

Then type `/why exception notes` or `/why src/widgets/config.py` in OpenCode.

## 6. Other agents

Any agent that can run shell commands can use DecRack the same way:

1. Install the CLI.
2. Put the contents of [`AGENTS.md`](../AGENTS.md) wherever that agent reads its standing instructions. Many read `AGENTS.md` at the project root directly.

`--format json` gives agents structured output; without it, the same commands print readable markdown for people.

- **Success:** every JSON result starts with `"ok": true`.
  - `why` returns `results` with a `decision_id`, `title`, `outcome`, `link` and `options`, and each option carries `status`, `status_kind`, `confidence`, `reason` and `link`.
  - `show <decision_id or pep:NNN> --detail evidence` returns the full `record`.
  - `check-pr` returns `paths`, `prs`, `matches` and `markdown`.
- **Failure:** a failed input check prints `{"ok": false, "error": "...", "fix": "..."}`, and the agent should pass that on to the user as it is. The README lists the cases and exit codes.

## 7. Troubleshooting

**The agent doesn't use DecRack.** Check that `AGENTS.md` is at the project root, and name DecRack in the prompt. Small models sometimes skip instructions; a larger agent model helps.

**The agent says there are no records.** Nothing has been compiled into the database it reads. Make sure the agent ran `decrack run <source>` first, against the same database (`DECRACK_DB`).

**DecRack reports that the model isn't ready.** Run `decrack doctor` and follow its fix: start Ollama, or `ollama pull qwen2.5:1.5b`.

**`decrack run` seems slow.** It should take about a minute for a small thread and several minutes for a long one; see the estimates in [TESTING.md](TESTING.md#7-what-to-expect). Cached calls make re-runs fast.

**GitHub sources fail.** `decrack run` needs `GITHUB_TOKEN` in its environment. Export it in the shell you start the agent from, then restart the agent so its shell inherits it.
