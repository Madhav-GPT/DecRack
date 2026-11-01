# DecRack Hackathon Declaration

## Project and team

- **Project:** DecRack
- **Team:** Allied
- **Problem statement:** PS6 — Open Source Decision Intelligence and Knowledge Recovery
- **Confirmed team members:** Madhav Gupta, Aish Sagwal, Kabir Vashisht, and Akshara Verma

## Project goal

DecRack is intended to recover decisions and their reasoning from historical technical discussions, issues, pull requests, and forums, then surface relevant decisions when someone changes related code.

## AI model the product uses

DecRack runs one open-weight model locally, through Ollama's native API (`http://127.0.0.1:11434` by default). It calls no hosted model API.

- **`qwen2.5:1.5b` via Ollama.** It is `DEFAULT_MODEL` in `src/decrack/config.py`. By default the pipeline calls it for one step, `map`: it labels what each post does and names the alternatives, citing sentence IDs, and code then checks every citation. Two optional steps use the same model and are off by default: the support check (`--support-check`) and the evaluation's closed-book baseline (`eval --closed-book`). `decrack chat` makes one more call, `answer`, which writes a short answer from the maintainers' words and the cited cards only.
- **Why this model:** it is about 1 GB, fast enough to run the whole pipeline on a 16 GB base M4 laptop, released under Apache-2.0, and it returns JSON-schema output through Ollama, which the pipeline validates before using it.

Real example outputs are produced with `decrack eval` on a local machine running Ollama.
