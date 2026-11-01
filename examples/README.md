# Examples

This folder holds **only real runs**: outputs of DecRack on the team's laptop, with a local open-weight model served by Ollama. Nothing here is hand-written, hand-edited or replayed from test recordings. Every run folder has a `run.json` naming the model that produced it, with its digest and the Ollama version.

The replayed model responses used by the tests live in `tests/fixtures/`, never here. Replay proves the pipeline logic; these runs prove that an open-weight model does the work.

CI checks this folder on every pull request. `decrack verify examples` (and the matching test in `tests/test_examples_invariants.py`) re-checks every record against the thread it came from:

- every quote must equal the sentences it cites;
- every quote must appear in its post;
- every option must have evidence;
- every folder under `runs/` must hold a `run.json` whose `mode` is `live`, so replayed or scripted output is refused.

The build fails if any check does.

## Layout

```text
examples/
├── runs/                        one folder per real run
│   ├── pep-0830/                an evaluation run (decrack eval)
│   │   ├── thread.json          the input, as DecRack ingested it
│   │   ├── records.json         the decision records built from the model's map output
│   │   ├── run.json             model, digest, Ollama version, settings, source allowlist, timings
│   │   ├── scores.json          the scores against eval/gold/pep-0830.json
│   │   └── matches.json         every predicted-to-gold pair, for human review
│   ├── pep-0799/ …              one folder per evaluated PEP
│   ├── uv-2077/                 a single run (decrack run REF --out examples/runs/<name>), no scores
│   ├── eval-summary.md          the evaluation results across all PEPs
│   └── eval-summary.json        the same, as JSON
└── okf/                         the OKF + MADR knowledge bundle (decrack export okf)
    ├── index.md
    ├── log.md
    └── decisions/
        ├── index.md
        └── dr-xxxxxxxx-<slug>.md   one markdown file per decision record
```

## What each file holds

| File | Contents |
|---|---|
| `thread.json` | The thread exactly as DecRack ingested it. Every post has its stable source ID, version, author, role, permalink, own text, sentence offsets and hash. For evaluation runs, the leak controls have already run: links to the PEP are refused, and an opening post that pastes the PEP is stripped. |
| `records.json` | A list of decision records. Each option has a status, a status kind (`confirmed`, `inferred`, `contested` or `unresolved`), a basis, a status history, reasons and a confidence tier. Each piece of evidence holds the post ID and version, the sentence indexes and offsets, the quote, the link, `source_check`, and `support`. `support` is `unchecked` unless the optional support check ran. |
| `run.json` | How the run was made: the model tag (`qwen2.5:1.5b`), the model digest (from Ollama's `/api/show`), the Ollama version, `num_ctx` and the other model parameters, whether the optional support check ran, the prompt and schema versions, the **source allowlist** (every post ID, version and hash given to the model), timings, model calls and tokens |
| `scores.json` | Evaluation runs only: recall, precision per status kind, reason agreement, evidence-backed recall, matches with evidence outside the opening post, search@5 with its `search_misses`, the closed-book baseline when it ran, and the verification metrics (pre-gate citation validity, and the support rate when the support check ran) |
| `matches.json` | Evaluation runs only: every predicted-to-gold pair from the deterministic fuzzy matching (there is no model judge), for a human to review |
| `eval-summary.md`, `eval-summary.json` | The same metrics across all evaluated PEPs. The README's results table comes from here. |
| `okf/` | The records rendered as an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) v0.2 bundle: OKF frontmatter, DecRack's fields under `decrack:`, and a MADR-style body (Question, Decision outcome, Considered options, Rejected ideas, Code, Evidence). OKF is only the file format; the records' source of truth is DecRack's SQLite database. |

## How to reproduce

On a machine with Ollama and `qwen2.5:1.5b` (see [docs/TESTING.md](../docs/TESTING.md)). The committed results cover PEPs 830, 799 and 806, which took 47 s, 40 s and 22 s to compile on a base M4 with 16 GB (measured in each `run.json`). The command below runs all eight PEPs that have gold sets:

```bash
uv run decrack eval pep:830 pep:799 pep:806 pep:836 pep:822 pep:844 pep:842 pep:810 \
  --gold eval/gold --out examples/runs --closed-book
uv run decrack export okf --out examples/okf
uv run decrack verify examples
```

A single run looks like this:

```bash
uv run decrack run https://github.com/OWNER/REPO/pull/NUMBER --out examples/runs/github-REPO-NUMBER
```

A run calls the model only the first time; every call is cached by a hash of its exact inputs. A re-run on another machine should match when the model digest in `run.json` matches.

## How to check a claim yourself

1. Pick an option in `records.json` and one of its evidence entries.
2. Find the post with that `post_id` in `thread.json`, or open the entry's `url`.
3. Check the quote. It is exactly the post's text from `start` to `end`: the sentences named by `sentence_indexes`. The model chose which sentences to cite, but code cut the quote from the post, so it is always the poster's exact words.
4. Check the claim. The `support` field says whether the optional support check found that these sentences support the claim. `unchecked`, the default, means the check didn't run.
5. Check the authority. The option's `status_kind` and `status_basis` say whether this was an explicit decision by the author or a decider (`confirmed`), or something weaker.
