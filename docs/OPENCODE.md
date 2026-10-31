# Use DecRack from OpenCode or any agent

There are two ways for an agent to use DecRack:

1. **MCP**, for OpenCode and any other MCP harness. `decrack mcp` gives the agent DecRack's tools.
2. **The CLI with [`AGENTS.md`](../AGENTS.md)**, for any agent that can run shell commands. The instruction file tells the agent which command to run when, and how to report what comes back.

People can skip agents entirely and use `decrack chat` in their own terminal (see the [README](../README.md#quickstart)). The chat only answers questions about decisions in a linked discussion. With no link, off-topic text or no match, it replies with its scope line: *"I answer questions about engineering decisions in a discussion: what was proposed, what was rejected or accepted, and why. Give me a link (a GitHub repo, issue or PR, a discuss.python.org thread, or pep:NNN) and a question."*

**Contents:** [How it works](#how-it-works) · [Install](#1-install) · [OpenCode over MCP](#2-add-decrack-to-opencode-over-mcp) · [CLI with AGENTS.md](#3-or-use-the-cli-with-agentsmd) · [OpenCode on a local model](#4-run-opencode-on-a-local-open-model) · [Example prompts](#5-example-prompts) · [/why command](#6-optional-a-why-command) · [Troubleshooting](#7-troubleshooting)

---

## How it works

- **DecRack's own open model does the reading.** It finds the model automatically: the one you name with `--model` if installed, otherwise `qwen2.5:1.5b`, otherwise any model the local Ollama runs. If Ollama isn't running or no model is installed, DecRack stops and prints the exact fix, such as *No open model installed. Run: ollama pull qwen2.5:1.5b*.
- **The agent's model never extracts.** It decides when to call DecRack, and explains the evidence that comes back.
- **A source comes first.** The source can be a GitHub repo URL, an issue or PR URL, a discuss.python.org thread, `pep:NNN` or a file. With a repo URL, DecRack searches the repo's issues and PRs for the question's keywords and reads the top 3.
- **Every answer is cited.** It is made of decision cards that cite the exact sentences they came from, and the agent should quote only that text and report each status kind (`confirmed`, `inferred`, `contested`, `unresolved`) honestly.

## 1. Install

```bash
uv tool install git+https://github.com/Madhav-GPT/DecRack
ollama pull qwen2.5:1.5b
decrack doctor
```

`uv tool install` puts `decrack` on your PATH; DecRack isn't on PyPI. `decrack doctor` checks Ollama, the installed models and `opencode`, and says how to fix anything that fails. By default the database is `decrack.db` in the current folder. To share one database across sessions, set `DECRACK_DB=/absolute/path/to/decrack.db`.

## 2. Add DecRack to OpenCode over MCP

Put this in `opencode.json` at the root of your project, or in `~/.config/opencode/opencode.json` to use it everywhere:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "decrack": {
      "type": "local",
      "command": ["decrack", "mcp"],
      "enabled": true,
      "environment": { "DECRACK_DB": "/absolute/path/to/decrack.db" }
    }
  }
}
```

The `environment` line is optional; it points the server at a shared database. Restart OpenCode. The agent then has these tools:

| Tool | Use it to… |
|---|---|
| `ask` | Answer a question about a source, compiling it first if needed: the same as `decrack ask` |
| `search_decisions` | Search the recorded decisions, and get compact cards back |
| `get_decision` | Read one record, as a card, in full, or with its evidence |
| `decisions_for_files` | List the decisions linked to files the agent is about to edit |
| `check_change` | Get the `check-pr` report for a PR URL or a list of paths |
| `search_evidence` | Search raw posts, labeled uncompiled, when no record matches |

There is also the `review_with_history` prompt. Only `ask` runs DecRack's model; the other tools only read the database.

**How OpenCode decides to use DecRack.** OpenCode picks tools from their descriptions, so users type normal prompts. DecRack's tool descriptions say when to use them, for example *"Use when the user asks why something was decided, rejected or accepted in a GitHub repo, issue or PR, a discuss.python.org thread or a PEP."*, and OpenCode calls the `ask` tool when a request matches. Naming DecRack in the prompt still helps small models.

**Other MCP clients** accept the same server in their own format. Most use this shape:

```json
{ "mcpServers": { "decrack": { "command": "decrack", "args": ["mcp"] } } }
```

## 3. Or use the CLI with AGENTS.md

Copy [`AGENTS.md`](../AGENTS.md) from this repository to the root of your project, or paste its sections into the `AGENTS.md` you already have. OpenCode and many other agents read it automatically. It tells the agent to:

1. Require a source and a question, and ask the user if either is missing.
2. Run `decrack ask <source> "<question>" --format json`.
3. Run `decrack show <id> --detail evidence --format json` before claiming anything.
4. Use `decrack why` for follow-ups, and `decrack check-pr <PR URL>` for changes.

It also tells the agent to quote only DecRack's text, link the evidence, report status kinds honestly, and relay DecRack's error and fix messages as they are. Every JSON result has `"ok": true`, and a failed check prints `{"ok": false, "error": "...", "fix": "..."}`.

## 4. Run OpenCode on a local open model

OpenCode can use models served by Ollama; set it up by following the Ollama section of OpenCode's [provider docs](https://opencode.ai/docs/providers/).

- **Pick any open model for the agent.** It is separate from DecRack's extraction model, and larger models follow instructions more reliably.
- **Raise Ollama's default context.** Ollama gives a model only 4K tokens on machines with less than 24 GiB of VRAM, and OpenCode can't raise it per request. Start Ollama with:

  ```bash
  OLLAMA_CONTEXT_LENGTH=32768 ollama serve
  ```

  This doesn't affect DecRack's own calls, which set their context size explicitly.
- **On a 16 GB laptop, compile threads before you start chatting,** so that the agent's model and DecRack's extraction don't compete for memory.

## 5. Example prompts

- *"Use DecRack on https://github.com/astral-sh/uv/issues/2077: why didn't uv add pip's --user flag?"*
- *"Use DecRack on https://github.com/owner/repo. Why didn't they add X?"* DecRack searches the repo's issues and PRs.
- *"Use DecRack on pep:830. Was attaching timestamps through exception notes rejected? Quote the evidence."*
- *"I'm about to edit `src/widgets/config.py`. Ask DecRack which recorded decisions cover that file."*
- *"Before I open this PR, check it with DecRack: https://github.com/owner/repo/pull/456."*

If a prompt names a repo but asks nothing, DecRack stops with *Tell DecRack what you want to know, e.g. decrack ask https://github.com/owner/repo "why not X?"*, and the agent should ask the user what they want to know.

## 6. Optional: a `/why` command

OpenCode turns markdown files in `.opencode/commands/` into slash commands. Save this as `.opencode/commands/why.md`:

```markdown
---
description: Ask DecRack why the code is the way it is
---
Use DecRack to find recorded decisions, rejected alternatives and their reasons related to: $ARGUMENTS

- Use the decrack ask or search_decisions tool (or, without MCP, the CLI as AGENTS.md describes).
- For the best match, get the decision with its evidence.
- Report each relevant option's status, status kind and reason, quoting DecRack's evidence exactly, with links.
- If DecRack has no record, say so and ask for a source to analyze. Don't guess.
```

## 7. Troubleshooting

**The DecRack tools don't show up.**
- Check that the JSON is valid and in the right file, then restart OpenCode.
- Run `decrack mcp` in a terminal. It should start and wait silently; press Ctrl-C to stop it.

**The agent says there are no records.** Nothing has been compiled into the database it reads. Ask through the `ask` tool or `decrack ask` first, and make sure both use the same `DECRACK_DB`.

**DecRack reports that the model isn't ready.** Follow the fix it prints: start Ollama, or `ollama pull qwen2.5:1.5b`. `decrack doctor` shows what is missing.

**Answers are slow.** A first read should take about a minute for a small thread and several minutes for a long one; see the estimates in [TESTING.md](TESTING.md#7-what-to-expect). Cached calls make re-runs fast.

**GitHub sources fail.** DecRack needs `GITHUB_TOKEN` in its environment. Export it in the shell you start OpenCode from, or add it to the MCP entry's `environment`, then restart OpenCode.

## Small local models (qwen2.5:1.5b): make sure DecRack gets called

A 1.5B model often answers from memory instead of calling a tool, especially next to OpenCode's many built-in tools. This repo's `opencode.json` fixes that. Run OpenCode inside the DecRack folder, or copy its `agent` and `command` blocks into `~/.config/opencode/opencode.json`:

- **The `decrack` agent** (press Tab to switch to it) has a short prompt and one tool, `decrack_ask`, so the model calls it instead of guessing.
- **The `/why` command** sends your message straight to that agent: `/why Why didn't uv add pip's --user flag? astral-sh/uv#2077`.
- **`"timeout": 600000`** gives the first read of a long thread up to 10 minutes. Later questions on the same thread are cached and instant. To warm the cache first, run `decrack ask astral-sh/uv#2077 "why not --user?"` in a terminal from the same folder, since the database (`decrack.db`) lives in the folder you start from.
- **Context length:** Ollama's default context is small (4,096 tokens on most laptops), which cuts off OpenCode's default prompt and tool list. The `decrack` agent fits in it. To use DecRack's tools from the default Build agent, start Ollama with a longer context: `OLLAMA_CONTEXT_LENGTH=16384 ollama serve`.
- **`ask` accepts the whole message.** If the model puts the user's entire message in `source`, DecRack finds the link and the question itself.

