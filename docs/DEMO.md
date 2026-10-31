# Demo script and judge Q&A

**Format** (from the organizers): an 8-minute pitch that includes the live demo, then 4 minutes of questions and a 2-minute buffer. Show the live demo, how it works, the models and tools used, and what we learned. **Judges can question any team member.**

The panel scores design and trade-offs, the live demo and usability, and problem understanding.

**Contents:** [Checklist](#before-you-go-on) · [Who presents](#who-presents-what) · [The 8 minutes](#the-8-minute-script) · [Fallbacks](#if-something-goes-wrong) · [Q&A cheat sheet](#judge-qa-cheat-sheet) · [Explain any module](#explain-any-module-in-one-breath) · [Numbers](#numbers-to-know)

---

## Before you go on

Do these 30 minutes before the slot, on the demo laptop, from the **tagged freeze commit**.

- [ ] **Laptop.** On power, notifications off, terminal font at about 20 pt, light theme.
- [ ] **Windows ready.** Two terminal tabs, OpenCode, and a browser.
- [ ] **Ollama.** It is running (`OLLAMA_CONTEXT_LENGTH=32768 ollama serve` if OpenCode uses a local model), and `uv run decrack doctor` passes every check.
- [ ] **`decrack.db` is precomputed:**
  - PEP 830, the demo thread (`uv run decrack run pep:830`);
  - the eval PEPs (`decrack eval`, see [TESTING.md](TESTING.md));
  - the GitHub example used for `check-pr`.
- [ ] **A card prints.** `uv run decrack why "exception notes"` shows the PEP 830 card. Note which rejected option you will point at, its status kind and its sentence alias.
- [ ] **OpenCode.** The demo project has DecRack's [`AGENTS.md`](../AGENTS.md) at its root, `decrack` is on the PATH, and `DECRACK_DB` points at the precomputed database.
- [ ] **`check-pr` input.** Find a path that is linked to a record (`uv run decrack why <path>` should return it), or prepare a branch for `--diff`.
- [ ] **Browser tabs:**
  - the PEP 830 thread, <https://discuss.python.org/t/106942>;
  - the green CI run on GitHub;
  - `examples/runs/eval-summary.md` and one `run.json` on GitHub.
- [ ] **Decide one thing in advance:** whether to run `decrack run pep:830` live or on the cache. A cold run should take under a minute on a base M4 with 16 GB, but that is an estimate until measured. Time it in rehearsal; if it is slower, precompute it and explain the cache.

---

## Who presents what

Each member presents the part they built, and each must be able to answer questions on the others. Fill in the names before rehearsal.

| Part | Presenter | Time |
|---|---|---|
| The problem and what DecRack is | Acquire owner | 0:00–1:30 |
| Live: compile a thread and ask why | Compile owner | 1:30–3:30 |
| Live: an agent asks first; the PR check | Store and Serve owner | 3:30–6:00 |
| Proof (eval and CI), then how it works and what we learned | Prove owner | 6:00–8:00 |

---

## The 8-minute script

### 0:00–0:45 · The problem

**Say:**
- Open-source projects make their decisions in public, and the reasoning gets buried. The discussion of one PEP, explicit lazy imports, ran to 464 posts.
- Nobody re-reads that before opening a pull request, so rejected ideas keep coming back.
- AI coding agents make it worse: they read the code and the docs, never the thread where the maintainers rejected the approach they are about to write.
- The organizers' test puts it exactly: hand over a PEP's discussion without the PEP, and recover the rejected ideas and why.

**Show:** the PEP 830 thread in the browser. Scroll it once, to show it is a real discussion.

### 0:45–1:30 · What DecRack is

**Say:**
- DecRack is decision memory for open-source projects: a CLI that people and coding agents use directly, with no UI. Agents follow one instruction file, `AGENTS.md`.
- Context7 gives agents library docs; DecRack gives agents a project's decisions and rejected ideas.
- In one line: an open model compiles discussions into verified decision records once. Code is connected by git facts, not embeddings. OKF is just the file format we export. Lookups are exact search, and any explanation is written by your agent from cited evidence.
- The open model is Qwen 2.5 1.5B (`qwen2.5:1.5b`), running locally in Ollama on DecRack's own code path. By default it does one job, the map step, and code does the rest.

**Show:** the "How it works" diagram in the README.

### 1:30–3:30 · Live: compile and ask why

```bash
uv run decrack doctor
uv run decrack run pep:830
uv run decrack why "exception notes"
```

**Say, while it runs:**
- **Acquire:** one request fetches the whole topic through the official JSON API. Every post keeps its stable ID and version, and every sentence its character offsets.
- **Roles:** they come from metadata. A Steering Council member is a decider because of their group membership, not because a post says so.
- **Map:** the open model reads the thread in token-budget windows, about 3,000 tokens each. For every post it labels the act (propose, object, reject…), names the alternatives and cites the sentences it relies on. That is its only job by default.
- **Everything else is code:** merging duplicates, collecting reasons, the status rules and confidence.
- **Three checks:**
  - the **gate** checks that each cited sentence exists in that post version, and slices the quote from the post;
  - the **status rules** decide whether it was a decision at all. That needs explicit decision language, such as "rejected" or "we will not", from the author or a decider;
  - an optional **support check**, off by default, can ask the model whether those sentences really support the claim.

**Say, if it's cached:** "We compiled this earlier. Every model call is cached by a hash of its exact inputs, so this re-run replays instantly, and the database keeps every prompt and response as an audit log."

**Show on the card:**
1. One **REJECTED** option, its **status kind** (confirmed or inferred) and its one-line reason.
2. Its post link: open it in the browser and find the cited sentence. It is the poster's exact words.
3. The **basis**: an author statement, a decider statement or participant consensus.

### 3:30–5:00 · Live: an agent asks before it codes

**Type in OpenCode:**

> I want to add timestamps to exceptions using exception notes. Before writing any code, ask DecRack whether that approach was already rejected, and why.

**Expected** (the agent follows `AGENTS.md`):
1. The agent runs `decrack why "exception notes" --format json` in its shell and gets compact cards. You can see the command.
2. It runs `decrack show <id> --detail evidence --format json` for the quotes and their surrounding posts.
3. It answers with the status, the status kind, the reason and the quoted evidence with its link.

**Say:**
- **Compact first, then expand.** The agent gets short cards, and asks for the evidence only when it needs it.
- **No model on the lookup.** The answer comes from stored records, so it is fast. The agent's own model writes the explanation, from cited evidence.
- **The agent can compile too.** For a thread DecRack hasn't seen, the agent runs `decrack run <source>`, and you see the command before it runs.
- **Agents are told to check first.** `AGENTS.md` tells any agent to ask for a source if there is none, check `show` before claiming anything, and report status kinds honestly.

**Optional, if time allows:** ask *"Analyze https://discuss.python.org/t/106942 with DecRack and tell me which ideas were rejected and why"*, and show the `run`, `why` and `show` commands it runs. The same demo also works from a plain terminal.

### 5:00–6:00 · Live: the PR check

```bash
uv run decrack check-pr --paths PATH/LINKED/TO/A/RECORD
# or, on a prepared branch of a local clone:
uv run decrack check-pr --diff main..demo-change --repo ../DEMO-REPO
```

**Say:**
- `check-pr` takes the files a change touches and finds the recorded decisions behind them.
- Links come only from exact facts, with three strengths:
  - **direct**: files and PRs the thread names;
  - **historical**: what git records, meaning the PR that changed the file, or, with `--blame`, `git blame` on the changed lines;
  - **suggested**: a search match.
- It reports related history and possible conflicts. It never says a change is invalid: a rejected idea can come back for good reasons, and that is the reviewers' call.
- It never posts on real projects: it is read-only by design.

### 6:00–7:00 · Proof

**Show:** `examples/runs/eval-summary.md` on GitHub.

**Say** (read the numbers off `eval-summary.md`, and rehearse them):
- **The method:** this is the withheld-PEP test, run ourselves. The gold comes from each PEP's Rejected Ideas section, with 59 items across 8 PEPs.
- **The metrics:**
  - the headline numbers are recall, precision per status kind, and evidence-backed recall;
  - the verification numbers are reported separately: the pre-gate citation validity of the model's real outputs, and the support rate when the support check ran;
  - matching to the gold is deterministic fuzzy matching, and a human reviews every pair in `matches.json`.
- **search@5:** for each matched idea, we run a plain keyword search over the extracted options, with the PEP's heading as the query, and ask whether the right option is in the top 5.
  - This number decides whether we need embeddings.
  - If keyword search misses ideas because the thread words them differently, we add vectors inside the same SQLite file, with an open embedding model through Ollama. Otherwise FTS stays as it is.
- **The leak controls:**
  - the PEP index is used only to find the discussion;
  - the PEP's status and resolution never reach a prompt;
  - an opening post that pastes the PEP is stripped;
  - every run records exactly which post versions the model saw.
- **The baseline:** compare the closed-book recall (the same model, given only the PEP's number and title) with DecRack's recall. That gap is what reading the thread adds.

**Show:**
1. One `run.json`: the model tag, its digest, the Ollama version and the source allowlist.
2. The green CI run: one job, "DecRack checks". Its steps lint and compile, run the offline tests on recorded responses, verify the examples, run the compliance scan and build the package.

**Say:** "CI proves the logic with replayed responses. The real runs prove the model, and we keep the two apart."

### 7:00–8:00 · How it works, models and tools, what we learned

**Show:** the one architecture diagram (Acquire → Compile → Serve, around one SQLite file).

**Models and tools:**
- The product uses `qwen2.5:1.5b` through local Ollama, on a base M4 MacBook Pro with 16 GB. It is the same tag in `HACKATHON.md`, in every PR and in every `run.json`.
- **The trade-off, honestly:** we chose a 1.5B model so the whole pipeline runs quickly on a base laptop. Accuracy is measured by the eval, not assumed. Every claim stays citation-checked, so lower recall means missed ideas, not unsupported claims. Bigger open models still work through `--model`.
- Name the AI coding assistants the team used during development, exactly as listed in the PRs.

**What we learned:**
1. Ollama silently cuts prompts to 4K tokens on small GPUs, so DecRack sets the context size on every call.
2. "Verified" is three questions: does the text exist, does it support the claim, and is it a decision? We check and report each one separately.
3. Small models are reliable when code owns the structure: IDs, roles, merging, status rules and quotes. That is why one narrow job is enough for a 1.5B model.
4. "Latest message wins" over-claims. A decision needs explicit decision language from someone with authority; otherwise the answer is `inferred`, `contested` or `unresolved`.
5. A fair evaluation needs leak controls, because many opening posts paste the PEP or preview it.

**Limitations:** a small model misses ideas, and recall is measured rather than assumed; the support check is optional and off by default; code links are file-level.

**Deferred, not abandoned:** a web UI, ACP harness control, timelines and graphs. They sit behind the same core/adapter boundary as the CLI.

**Close:** "Before an agent writes code, it should know what the project already rejected, and why. That's DecRack."

---

## If something goes wrong

| If… | Then… |
|---|---|
| The Wi-Fi is down | Everything except fetching a new thread works offline from `decrack.db`. Skip `ingest`, and show the cached run. |
| The model is slow, or Ollama crashes | Use the cached run, which replays instantly, or open the committed outputs in `examples/runs/` and `examples/okf/`. Explain the cache: that is the "compile once" principle. |
| OpenCode doesn't run DecRack | Ask it explicitly ("use DecRack"), or run `/why exception notes`. If needed, run the same commands yourself in the terminal: `uv run decrack why "exception notes"`, then `uv run decrack show <id> --detail evidence`. |
| `check-pr` finds nothing | Use `--paths` with a path you checked beforehand with `decrack why <path>`. |
| `why` finds no record for a judge's question | Run `uv run decrack why --raw "..."`. It searches the raw posts and labels them uncompiled, so say clearly that they haven't been through the checks. |
| A judge asks for another PEP | Run `decrack run pep:N` in the second tab while you keep talking, or ask the OpenCode agent to run it through its shell. Small threads should finish in about a minute (an estimate); for a long one, move on and come back to it. |

---

## Judge Q&A cheat sheet

Short, true answers. The detail behind each one is in [ARCHITECTURE.md](ARCHITECTURE.md).

### Problem understanding

**What problem are you solving?**
Projects lose the reasoning behind their decisions in long threads. People and agents re-propose rejected ideas because nothing tells them "this was tried, and here is why it was rejected." DecRack recovers that reasoning with evidence, and serves it where the work happens: the agent, the terminal, the repo and CI.

**Why start with PEPs?**
PEPs are the organizers' test. Their discussions are public, long and messy, and every PEP's Rejected Ideas section gives us an answer key to measure against. Nothing in the pipeline is specific to PEPs: GitHub issues and PRs, any Discourse forum and exported files all work too.

**Who uses it?**
- Coding agents, before they write code, through the CLI and `AGENTS.md`.
- Reviewers and maintainers, through `check-pr` on pull requests.
- Newcomers, through `decrack why` and the markdown bundle.

**How is this different from Context7, or a chatbot over the code?**
Context7 serves library documentation. Code chatbots answer questions about the code as it is now. DecRack serves the project's decisions: what was considered, what was rejected, by whom, how firmly and why, with sentence-level evidence.

### Design and trade-offs

**Is this RAG? A knowledge graph?**
Neither.
- **No RAG over code:** we never embed the codebase.
- **Extraction, once:** an open model reads the discussion once, labeling posts and citing exact sentences, and code builds the decision records.
- **Linking by facts:** code is linked by git facts (which PR changed which file, `git blame`) and by paths the thread names.
- **OKF is only a format:** one markdown file per decision. It isn't a graph engine and doesn't retrieve anything.
- **Lookups are exact or keyword search, with no model.** If the user's agent explains anything, it does so from the cited evidence we return.

**How do you know a "rejected idea" is real?**
Three separate checks:
1. **Source validity.** The cited sentence exists in that version of the post. That is checked by code, and the quote is sliced from the post.
2. **Decision authority.** It counts as a decision only if the author or a decider used explicit decision language in the cited sentence, such as "rejected", "added to rejected ideas", "we will not" or "decided". Code matches a fixed cue list; the model doesn't decide this.
3. **Semantic support, optional.** With `--support-check`, a batched model call asks whether those sentences support the claim. It is off by default, and records then say `support: unchecked`.

Click the link to see the sentence in the thread.

**How do you tell accepted from rejected?**
Every option has a status and a status kind:
- **confirmed:** an accept, reject or defer by the author or a decider, in explicit decision language from the cue list;
- **inferred:** the author's objection without that language, or objections from at least two participants, with no authoritative backing;
- **contested:** a later post by the author or a decider points the other way;
- **unresolved:** everything else.

A later statement replaces an earlier one only if it uses explicit decision language and comes from the same or higher authority. We don't do "latest message wins".

**What if the model hallucinates?**
- **Citations to text that doesn't exist** are dropped by code.
- **A real but wrong citation** is the harder case. Status needs explicit decision language from someone with authority, which a stray citation rarely has.
- **The optional support check** (the global `--support-check` flag) sees only the claim and the cited sentences. A claim it judges unsupported is downgraded from `confirmed` to `inferred`.
- **With the check off,** which is the default, records say `support: unchecked`, never "verified".

We measure the model's pre-gate citation validity, and its support rate when the check runs, and report them instead of assuming them.

**What if a discussion has no clear outcome?**
Then DecRack says so: `inferred`, `contested` and `unresolved` are first-class, and confidence comes from evidence, never from the model's own estimate.

**What about prompt injection in a forum post?**
- Extraction calls have no tools and no secrets.
- Posts are wrapped in tags and datamarked.
- The model can only return schema-shaped JSON, and only citations that pass the gate survive.
- A decision needs an authoritative role plus explicit decision language, so a post claiming "the Council accepted this" does nothing unless a decider wrote it.
- `AGENTS.md` tells agents to treat quoted discussion text as data, never as instructions.

**Why no vector database?**
Our search runs over a few hundred verified records with exact identifiers, and search@5 measures whether keyword search is enough.
- **If search@5 shows misses** caused by different wording, we add vectors inside the same SQLite file: `sqlite-vec` with an open embedding model via Ollama, fused with the keyword results.
- **Otherwise SQLite FTS stays:** one file, no server.

**Why OKF?**
It's a portable markdown file format with provenance fields that people and agents can read. It stays a generated export; SQLite is the source of truth.

**Why no MCP?**
Every agent harness can run a command. A CLI plus `AGENTS.md` is simpler to install, explain and test, and has one dependency fewer. Every step is also a visible shell command that the user can see and approve.

**Why only a CLI, with no UI?**
Developers already work in their agent, their terminal, their repo and CI, and a CLI reaches all of them. The UI is deferred, not abandoned: a web UI, ACP harness control, timelines and graphs would be one more adapter over the same core library.

**Do old decisions decay?**
No. A ten-year-old rejected idea can be the most relevant record there is. Age is shown as metadata. Whether a record still applies comes from its code links (does the linked file still exist?) and from later decisions.

**What did you take from Cerebras's knowledge-base write-up?**
- **Taken:** compact-first retrieval, and keeping raw evidence separate from interpretations.
- **Taken, half:** raw-evidence search as a fallback.
- **Not taken:** age decay, and filters that throw away short or unpopular posts. A short objection is often the very evidence we need.
- **Not taken:** Postgres and pgvector; our evidence is relational.
- **Test first:** hybrid vector search, decided by search@5.

It's a design write-up, not a benchmark, so we treat its ideas as things to test.

**Why a 1.5B model?**
We chose `qwen2.5:1.5b` so the whole pipeline runs quickly on a base laptop: a base M4 MacBook Pro with 16 GB and a download of about 1 GB, with no credentials and no data leaving the machine.
- **We measure accuracy instead of assuming it.** The eval reports recall, precision and the closed-book baseline for this exact model.
- **Lower recall never means unsupported claims.** Every claim stays citation-checked, so lower recall means missed ideas, not unsupported claims.
- **The design keeps the model's job narrow.** It labels posts in short windows; code does everything else.
- **Bigger open models still work** through `--model`, and the same eval shows what they would buy.

**Where does the open model do meaningful work?**
It is the extractor on DecRack's main path. By default it does exactly one job, the map step: it reads every window, labels what each post does, names the alternatives and cites the sentences. Every decision record is built from that output, and code does the rest. The optional support check and closed-book baseline also use it.

Every run in `examples/runs/` was produced by it. Each `run.json` records the model tag, its digest and the Ollama version, and `HACKATHON.md` names the same tag.

**Did the PEP leak into your evaluation?**
- The resolver uses the PEP index only to find the discussion URLs.
- The PEP's status, resolution and title suffix never enter a prompt.
- Links to the PEP are refused, and opening posts that paste the PEP are stripped.
- Each run records a source allowlist, so you can see exactly which post versions the model saw.
- We report a closed-book baseline next to our recall, plus evidence-backed recall.
- PEP 810 is a separate control, because models may know it.

**How does CI test without a model?**
- Tests replay recorded and scripted model responses (`DECRACK_LLM=replay`), and HTTP connectors run against saved payloads, so the real parsing, gating and status code runs with no network or model.
- That proves the logic, not the model. The model's evidence is the real runs in `examples/runs/`, which CI re-checks with `decrack verify`. We never mix the two.

**What happens when files are renamed?**
A link stores the path it had at the time. With a local clone, `git log --follow` resolves it to the current path. `check-pr --diff … --blame` also blames the changed lines back to the PRs that last touched them; the blame-walk is opt-in because it is slow on big repositories.

**Can you recognize the same person across platforms?**
No, deliberately. We'd only link accounts from exact evidence, such as a linked profile or the same commit email. Guessing from similar names risks false merges.

**Does it post comments on real projects?**
Never. `check-pr` prints related history and possible conflicts, or writes JSON. The rules forbid automated comments on real projects, and the design doesn't need them.

**How fast is it?**
Lookups are instant: they are SQLite reads with no model. A compile makes one model call per window of about 3,000 tokens. Our estimates, until measured, for a base M4 with 16 GB:
- about 6–8 seconds per call;
- under a minute for PEP 830's 29 posts;
- about 5–7 minutes for the whole 5-PEP evaluation.

Re-runs are free, because every call is cached. The measured numbers are in each `run.json`.

**What's not finished?**
Be honest and specific:
- Mailing-list archives (older PEPs) aren't supported; an exported file is the workaround.
- Code links are file-level.
- Identities aren't merged across platforms.
- Name anything else that didn't land by the freeze.

**What would you do next?**
Only measured steps:
- hybrid search, if the eval shows vocabulary misses;
- a recall-oriented second map pass, if it measures well;
- function-level code links;
- a mailing-list connector;
- the deferred UI.

---

## Explain any module in one breath

Rehearse until every member can say each line without notes.

| Module | One-breath explanation |
|---|---|
| `models.py` | The shared contracts: Thread, Post, Evidence, Option, DecisionRecord. Every module builds against them. |
| `config.py` | Settings from defaults, the environment (`DECRACK_DB`, `DECRACK_LLM`) and flags; there is no config file. The Ollama host can only be changed with `--ollama-host`. |
| `text.py` | Splits posts into sentences with character offsets, and hashes the normalized text. |
| `sources/discourse.py` | One request per topic (`/t/{id}.json?print=true`). It converts rendered HTML to text and keeps quotes as reply edges. |
| `sources/peps.py` | The PEP index's discussion links only. It merges the PEP's topics into one thread, never fetches the PEP, and keeps its status and resolution out of prompts. |
| `sources/github.py` | The REST API for issues, PRs, reviews and files, with a read-only token from the environment. |
| `sources/files.py` | Loads an exported thread from disk: the safety net for unknown input formats. |
| `pipeline/roles.py` | Roles from metadata: Steering Council group means decider; topic creator or PEP author means author; committers means maintainer. |
| `pipeline/windows.py` | Token-budget windows of about 3,000 tokens, with a small overlap of whole posts, splitting oversized posts at sentence boundaries. |
| `pipeline/llm.py` | Ollama's `/api/chat` with a JSON schema and an explicit context size (8,192). Every call is cached by a hash of its inputs, and replay mode serves the tests. |
| `pipeline/extract.py` | The map step, the model's one job by default: one call per window, carrying a header and the alternatives found so far. |
| `pipeline/gate.py` | Source validity: resolves citations to stable references, checks the post version and slices the quote. |
| `pipeline/support.py` | The optional support check, off by default (`--support-check`). Batches of about 8 claims, each judged supported, partial or unsupported from only the claim and its cited sentences. Off, every claim says `support: unchecked`. |
| `pipeline/consolidate.py` | All code: merges duplicates by string similarity, collects reasons, applies the status rules (decision language from the cue list, plus the speaker's role) and derives confidence. |
| `store.py` | One SQLite file in WAL mode: threads, posts and their versions, decisions, code links, every model call, and FTS5 search. |
| `search.py` | `why`: compact cards first, from FTS5 search or path lookup, within a token budget. `why --raw` searches the raw posts. |
| `linking.py`, `surface.py` | Code links (direct, historical, suggested) and the `check-pr` report of related history and possible conflicts. The blame-walk is opt-in with `--blame`. |
| `export_okf.py` | Writes the OKF v0.2 bundle with a MADR-style body. |
| `verify.py` | Re-checks every quote in every run folder against its thread. |
| `evaluate.py` | The withheld-PEP evaluation: deterministic fuzzy matching to the gold (with `matches.json` for human review), metrics per status kind, and the optional closed-book baseline. |
| `cli.py`, `doctor.py` | The `decrack` command (nine commands; `run` is how new discussions get in), and the environment check. |

---

## Numbers to know

| Number | What it is | How to say it |
|---|---|---|
| 29 / 464 | Posts in the PEP 830 thread / the PEP 810 thread | Fact (counted 1 Nov 2026) |
| 4K | Ollama's default context below 24 GiB of VRAM | Fact (Ollama docs) |
| `qwen2.5:1.5b`, ~1 GB | The model and its download size | Fact |
| 8,192 | The context size DecRack sets on every call | Fact (our setting) |
| ~3,000 | Window budget, in tokens | Fact (our setting) |
| 6–8 s / 5–7 min | Per model call / the full 5-PEP eval, on a base M4 with 16 GB | Estimate until measured |
| ~8 | Claims per batched support call, only with `--support-check` | Fact (our setting) |
| 59 (43 + 16) | Gold rejected ideas: the dev and stretch PEPs, plus the control | Fact (`eval/gold`) |
| search@5 | Matched gold ideas whose option ranks in the top 5 of a keyword search on the PEP heading | Read it from `eval-summary.md`; it decides whether embeddings are needed |
| 9 | CLI commands | Fact |
| 1 | CI job ("DecRack checks"), with lint, tests, verify, compliance and build steps | Fact |
| ~32K | Where Llama-3.1-8B stops being reliable on RULER | A synthetic benchmark; used for window sizing only |
| 44.4 vs 34.3 | OP-RAG F1: 16K tokens of in-order context vs a 70B model reading 117K | QA datasets; motivation, not proof for our task |
| 60 / 5,000 | GitHub requests per hour, anonymous / with a token | Fact (GitHub docs) |
