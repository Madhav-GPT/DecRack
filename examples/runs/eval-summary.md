# Withheld-PEP evaluation

DecRack read each PEP's discussion threads, never the PEP itself, with `qwen2.5:1.5b` (digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`) in local Ollama 0.40.13, prompt version `decrack-prompts-3`, run mode `live`. The options it predicted as rejected were matched one-to-one against the PEP's Rejected Ideas in `eval/gold/` by deterministic fuzzy matching (difflib + word overlap), threshold 0.5; no model judges the pairs. Every gold idea's match, or closest option, is listed in `pep-NNNN/matches.json` for review, and each PEP's model, digest, parameters and source allowlist are in `pep-NNNN/run.json`.

- **Predicted rejected**: options with a rejected, withdrawn, deferred or superseded status whose status kind is confirmed (an author's or decider's decision whose cited sentence has a decision cue) or inferred (weaker evidence). Contested and unresolved options are not predictions. The brackets split them into confirmed / inferred.
- **Recall**: share of the recoverable gold ideas that were matched.
- **Strict precision**: share of the predicted rejected options that match a gold idea. Valid rejections the PEP does not list count against it.
- **Precision, confirmed / inferred**: strict precision within each status kind; – when a kind has no predictions.
- **Reason agreement**: share of matches whose recovered reason says what the PEP says.
- **Evidence-backed recall**: recall counting only matches with a checked quote that shares words with the gold idea.
- **Matched outside post 1**: matches with evidence outside the opening post, which often restates the PEP.
- **Closed-book recall**: recall of the same model shown only "PEP N: title", with the title from the gold file.
- **search@5**: share of the matched gold ideas whose paired option comes back in the top 5 of DecRack's model-free keyword search (BM25 over every option of this run: titles, reasons and quotes) when the query is the gold idea's heading. Misses are listed in `pep-NNNN/scores.json`.

The last row sums the counts and averages the ratios over the PEPs with a gold file.

| PEP | Posts | Options | Predicted rejected (confirmed / inferred) | Gold (recoverable) | Matched | Recall | Strict precision | Precision, confirmed | Precision, inferred | Reason agreement | Evidence-backed recall | Matched outside post 1 | Closed-book recall | search@5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 830 | 29 | 4 | 3 (0 / 3) | 13 (13) | 1 | 0.077 | 0.333 | – | 0.333 | 1.000 | 0.077 | 1 | 0.231 | 1.000 |
| 799 | 22 | 5 | 1 (0 / 1) | 4 (4) | 0 | 0.000 | 0.000 | – | 0.000 | 0.000 | 0.000 | 0 | 0.000 | – |
| 806 | 29 | 4 | 1 (1 / 0) | 5 (5) | 0 | 0.000 | 0.000 | 0.000 | – | 0.000 | 0.000 | 0 | 0.200 | – |
| **Macro average** | 80 | 13 | 5 (1 / 4) | 22 (22) | 1 | 0.026 | 0.111 | 0.000 | 0.167 | 0.333 | 0.026 | 1 | 0.144 | 1.000 |
