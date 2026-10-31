# DecRack Hackathon Declaration

## Project and team

- **Project:** DecRack
- **Team:** Allied
- **Problem statement:** PS6 — Open Source Decision Intelligence and Knowledge Recovery
- **Confirmed team members:** Madhav Gupta, Aish Sagwal, Kabir Vashisht, and Akshara Verma

## Project goal

DecRack is intended to recover decisions and their reasoning from historical technical discussions, issues, pull requests, and forums, then surface relevant decisions when someone changes related code.

## Planned AI model strategy

DecRack is intended to support open-weight models running locally on users' machines. The system is planned to be model-agnostic, with room for additional compatible open-weight models and local runtimes.

- **Provisional candidate for evaluation: Qwen3-4B** ([model card](https://huggingface.co/Qwen/Qwen3-4B)). Its Apache-2.0 license is permissive, it has local deployment options, and its size makes it a candidate to evaluate for structured extraction of decisions and reasons from technical discussions. Its suitability for DecRack still needs to be tested.
- **Possible integration layer:** An existing compatible agent or harness such as OpenCode may be configured to use a local open-weight model through a runtime such as Ollama. OpenCode is an integration option, not an AI model.
- **Status:** An Ollama-compatible local inference adapter is implemented in the current development branch, but has not been tested against a running model. Qwen3-4B remains a provisional candidate and has not been run in DecRack. No open-source model scoring claim is made until a real model integration and demonstration are completed.

