# DecRack Hackathon Declaration

## Project and team

- **Project:** DecRack
- **Team:** Allied
- **Problem statement:** PS6 — Open Source Decision Intelligence and Knowledge Recovery
- **Confirmed team members:** Madhav Gupta, Aish Sagwal, Kabir Vashisht, and Akshara Verma

## Project goal

DecRack is intended to recover decisions and their reasoning from historical technical discussions, issues, pull requests, and forums, then surface relevant decisions when someone changes related code.

## AI models the product uses

DecRack runs open-weight models locally through Ollama's native API (`http://127.0.0.1:11434` by default). It calls no hosted model API.

- **`qwen3.5:4b` via Ollama, the default.** It is `DEFAULT_MODEL` in `src/decrack/config.py`. The extraction pipeline calls it to label what each post does and name the alternatives (`map`), to merge duplicate alternatives (`merge`), to refine reasons (`refine_reasons`) and to check that each claim is supported by its quotes (`support`). The evaluation also uses it as the matching judge (`judge`) and for the closed-book baseline (`closed_book`). Why: it is small enough to run on a 16 GB laptop and returns schema-constrained JSON, which the pipeline validates before using it.
- **`gemma4:e4b` via Ollama, the supported alternative.** It is listed in `ALTERNATIVE_MODELS` in `src/decrack/config.py` and selected with `decrack --model gemma4:e4b`. Why: a second open-weight model family of similar size, for machines or comparisons where Qwen is not the right fit.

Real example outputs are produced with `decrack eval` on a local machine running Ollama.
