# Withheld-PEP evaluation: gold sets

The PS6 evaluation gives DecRack the discuss.python.org threads for a Python
Enhancement Proposal (PEP), but not the PEP itself, and checks whether it
recovers the ideas the PEP rejected and why. This folder holds the answer key
for running that check ourselves, built from the "Rejected Ideas" sections of
recent PEPs.

```
eval/
  README.md          this file
  gold/
    pep-0799.json    one gold set per PEP
    ...
```

## Gold file format

```json
{
  "pep": 830,
  "title": "Add timestamps to exceptions and tracebacks",
  "status": "Draft",
  "topics": ["https://discuss.python.org/t/106942"],
  "python_peps_commit": "e931180fc33ecad5a82e68ee86928f486c9ec3bb",
  "leak_flags": [],
  "items": [
    {"id": "pep830-r1", "idea": "Using Exception Notes", "reason": "...", "recoverable": null}
  ]
}
```

| Field | Meaning |
|---|---|
| `pep`, `title`, `status` | From the PEP index. Inline markup is removed from the title. |
| `topics` | The discuss.python.org threads that are the evaluation input, in posting order. |
| `python_peps_commit` | The python/peps commit the items were parsed from. |
| `leak_flags` | Opening posts that paste PEP text (see [Leak rules](#leak-rules)). Empty means clean. |
| `items[].id` | `pep<N>-r<k>`, numbered in the order the ideas appear in the PEP. |
| `items[].idea` | The rejected idea: the subsection heading, as plain text. |
| `items[].summary` | Optional. Only on the 28 items whose first paragraph just introduces the idea: that paragraph, as plain text. |
| `items[].reason` | Why the PEP rejected the idea, as plain text. Usually the subsection's first paragraph; for the 28 items above, the sentences that give the reason (see [Reason sentences](#reason-sentences)). |
| `items[].recoverable` | Whether the threads contain enough to recover this item (see below). |

## How the gold sets were built

All sources were read anonymously on 1 Nov 2026.

1. **PEP metadata.** `https://peps.python.org/api/peps.json` (fetched once)
   gave each PEP's title, status, `discussions_to` and `post_history`.
2. **Topics.** Every discuss.python.org topic in `post_history` and
   `discussions_to`, deduplicated by topic ID. A link to a single post
   (such as `t/108515/152`) counts as its topic. The result matched the
   topic list we had researched beforehand exactly, so no topics were added.
3. **PEP sources.** An anonymous shallow clone of `https://github.com/python/peps`
   at commit `e931180fc33ecad5a82e68ee86928f486c9ec3bb`
   (2026-10-31, "PEP 11: Add Malcolm Smith as Android contact (#5210)").
   Files: `peps/pep-NNNN.rst`.
4. **Parsing rules.**
   - The section is the top-level heading named "Rejected Ideas", "Rejected
     Alternatives" or "Rejected Alternative Proposals". PEP 799 uses
     "Rejected Alternatives"; the other seven use "Rejected Ideas".
   - Each subsection heading directly under that section is one idea.
   - The reason is the plain text of the subsection's first paragraph:
     the first run of non-blank lines, skipping RST comments and link targets.
     When that paragraph only introduces the idea, it moves to `summary` and
     the reason sentences are picked from later in the subsection
     (see [Reason sentences](#reason-sentences)).
   - If a PEP listed its ideas as bullets instead of subsections, the bullets
     would be the ideas. None of the eight PEPs needed this.
   - Converting RST to plain text: inline literals lose their backticks;
     `:pep:` roles become "PEP N"; other roles become their text;
     a `:ref:` to a section becomes that section's title; hyperlinks become
     their link text; emphasis markers and footnote references are dropped;
     a trailing `::` becomes `:`; line breaks become spaces.
   - Only the rejected section counts. Neighbouring sections such as
     "Open Issues", or PEP 810's "Deferred Ideas" and "Alternate Implementation
     Ideas", are not gold items.
5. **Leak check.** Post 1 of every topic was fetched from
   `https://discuss.python.org/t/{id}.json` and checked against the rules
   below. The posts that `post_history` points at mid-thread
   (`t/106942/27`, `t/108515/152`, `t/108266/9`) were checked the same way.
   All three are clean.

## What `recoverable` means

`recoverable` says whether the threads in `topics` contain enough for a reader
to recover the idea and its reason, without the PEP.

- The team sets it to `true` or `false` after skimming the thread.
- `null` means not reviewed yet, and **counts as recoverable**. Every item
  starts as `null`.
- Set `false` when the idea or its reason never comes up in the listed
  threads, for example because it was settled in an earlier thread, or the
  author added it while editing the PEP. Items marked `false` should not count
  against the extractor.

## Leak rules

The evaluation is only fair if the extractor sees discussion, not the PEP.

1. **The extractor must never read `eval/gold/`.** That covers file access,
   prompts, few-shot examples and retrieval indexes. Only the scorer reads
   the gold files.
2. **Opening posts that paste the PEP get stripped.** A topic's post 1 is
   flagged if it has a "Rejected Ideas" (or "Rejected Alternatives"),
   "Abstract" or "Specification" heading, or more than 20,000 characters of
   text. A heading means a Markdown heading, a bold-only line, or an RST
   underlined title. A flagged post 1 is removed before the thread reaches the
   extractor. Each flag is recorded as `"t/<topic> post 1: <reason>"`.
3. **Links to the PEP are blocked.** The extractor must not follow links to
   `peps.python.org/pep-NNNN`, the PEP's file in python/peps, or any copy of
   either. Discourse turns a bare PEP link into a preview box
   (`<aside class="onebox">`) that embeds the PEP's opening text, so strip
   those previews as well as the links. Nine of the eleven opening posts link
   to their PEP; only `t/92939` and `t/108266`, the two early Ideas threads,
   do not.

Two opening posts were flagged. Both paste PEP sections into the post body,
but neither pastes the rejected section:

- `t/103971` (PEP 806) pastes the Abstract.
- `t/105519` (PEP 822) pastes the Abstract and Motivation.

Later replies can still quote PEP text. This check covers only the opening
posts and the three `post_history` posts.

## Gold sets

Post counts are each topic's `posts_count` on 1 Nov 2026.

| PEP | Title | Status | Topics (posts) | Ideas | Leak flags |
|---|---|---|---|---:|---|
| 830 | Add timestamps to exceptions and tracebacks | Draft | t/106942 (29) | 13 | none |
| 799 | A dedicated profiling package for organizing Python profiling tools | Final | t/100898 (22) | 4 | none |
| 806 | Mixed sync/async context managers with precise async marking | Rejected | t/92939 (15), t/103971 (14) | 5 | t/103971 post 1: Abstract heading |
| 836 | JIT Go Brrr: The Path to a Supported JIT Compiler for CPython | Withdrawn | t/108010 (84) | 5 | none |
| 822 | Dedented Multiline String (d-string) | Draft | t/105519 (152) | 5 | t/105519 post 1: Abstract heading |
| 844 | public and private builtins | Draft | t/108515 (151) | 5 | none |
| 842 | Module Exports | Withdrawn | t/108266 (19), t/108353 (165), t/108460 (134) | 6 | none |
| 810 (control) | Explicit lazy imports | Final | t/104131 (464) | 16 | none |
| **Total** | | | **1,249 posts** | **59** | **2** |

PEP 810 is a **control**. It was widely discussed in October 2025 and models may
have seen the PEP during training, so a good score on it does not show recovery
from the thread. Report it apart from the other seven PEPs (43 ideas).

## Reason sentences

In 28 subsections the first paragraph only introduces the idea, often ending
in "For example:" before a code sample, and the reason comes later. These
items differ from the rest:

- `reason` holds the one to three sentences from the same subsection that say
  why the idea was rejected. They are copied word for word, as plain text, in
  the PEP's order, and may come from different paragraphs.
- `summary` holds the first paragraph. A trailing "For example:" is dropped,
  and a final colon becomes a period.

| PEP | Items |
|---|---|
| 830 | r3, r4 |
| 806 | r1, r2, r3, r4, r5 |
| 822 | r2, r3, r4, r5 |
| 844 | r1, r2, r3, r4 |
| 842 | r1, r3, r4, r5, r6 |
| 810 | r3, r6, r7, r11, r13, r14, r15, r16 |

Three items have exceptions:

- `pep844-r2` (Add a new `__export__` variable) only says "See Why __all__
  and not __export__." Its reason comes from that section, under
  "Relationship to PEP 842 and PEP 843".
- `pep810-r16`'s `summary` also includes the three options that its first
  paragraph introduces.
- `pep810-r15`'s reason ends with a colon in the PEP, because a list follows.
  The colon becomes a period.

The other 31 items keep the first paragraph as `reason` and have no `summary`.
Picking the reason sentences was a judgment call, so check them during the
`recoverable` skim.

## Known caveats

- **`pep822-r1` (`str.dedent()` method)** is listed under Rejected Ideas, but the
  PEP says it does not reject the idea. Consider marking it `false` or
  scoring it separately.
- **Related threads not in `topics`.** The PEPs and opening posts link to
  older threads that are not part of the evaluation input. The opening post of
  `t/105519` lists `t/30127`, `t/35907`, `t/40679` and `t/90988`, and PEP 822's
  rejected section cites `t/40679` and `t/90988`. PEP 836 cites `t/107737`, and
  its opening post links `t/107638`. PEP 842 cites `t/104994`. PEP 844
  cites `t/108353`, one of PEP 842's threads. Ideas settled in those threads
  may need `recoverable: false`.
- **The gold sets are frozen at the pinned commit.** Draft PEPs (830, 822, 844)
  can still change upstream. Re-parse from a newer commit only on purpose,
  and update `python_peps_commit` when you do.

## How `decrack eval` uses these files

- **Who reads them.** `decrack eval pep:830 … --gold eval/gold --out examples/runs` reads these files only after extraction, so the extractor never sees them. The model is `qwen2.5:1.5b` via Ollama.
- **How predictions are matched.** Matching is deterministic fuzzy string matching, with no model judge.
- **What it writes.** Each PEP gets a run folder, `examples/runs/pep-NNNN/`, holding:
  - `thread.json`;
  - `records.json`;
  - `run.json`;
  - `scores.json`;
  - `matches.json`, which lists every predicted-to-gold pair for a human to review.

  The results across all PEPs go to `examples/runs/eval-summary.md`.
