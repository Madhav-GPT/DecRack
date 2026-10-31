---
type: "Decision Record"
title: "PEP 799 – A dedicated profilers package for organizing Python profiling tool"
description: "5 options: 1 rejected, 4 unresolved. Question: PEP 799 – A dedicated profilers package for organizing Python profiling tool"
resource: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898"
tags:
  - "decrack"
  - "pep-799"
  - "rejected"
  - "unresolved"
status: "draft"
generated:
  by: "decrack/0.1.0"
  at: "2026-10-31T22:47:54Z"
sources:
  - id: "dpo-100898-264174"
    resource: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/1"
    title: "Post #1 by pablogsal"
    author: "human:pablogsal@discuss.python.org"
    last_modified: "2025-08-01T14:28:45Z"
  - id: "dpo-100898-264197"
    resource: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/3"
    title: "Post #3 by pablogsal"
    author: "human:pablogsal@discuss.python.org"
    last_modified: "2025-08-01T16:20:25Z"
  - id: "dpo-100898-264212"
    resource: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/4"
    title: "Post #4 by guido"
    author: "human:guido@discuss.python.org"
    last_modified: "2025-08-01T17:30:01Z"
  - id: "dpo-100898-264214"
    resource: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/6"
    title: "Post #6 by pablogsal"
    author: "human:pablogsal@discuss.python.org"
    last_modified: "2025-08-01T17:34:06Z"
  - id: "dpo-100898-264266"
    resource: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/7"
    title: "Post #7 by Jelle"
    author: "human:Jelle@discuss.python.org"
    last_modified: "2025-08-02T00:28:39Z"
  - id: "dpo-100898-264267"
    resource: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/8"
    title: "Post #8 by pablogsal"
    author: "human:pablogsal@discuss.python.org"
    last_modified: "2025-08-02T01:04:14Z"
decrack:
  schema: "decrack-record/0.2"
  id: "dr-283f30d1"
  question: "PEP 799 – A dedicated profilers package for organizing Python profiling tool"
  thread_id: "pep:799"
  decided_by:
    handle: "pablogsal"
    role: "author"
  decided_in_post: "dpo:100898:264174"
  verification: "unverified"
  model: "qwen2.5:1.5b"
  run_mode: "live"
  prompt_version: "decrack-prompts-3"
  support_checked: false
  options:
    - key: "A1"
      title: "profiling"
      summary: "The proposal aligns with the goal of providing a unified, high-performance profiler for Python, which is beneficial for observability and"
      status: "unresolved"
      status_kind: "unresolved"
      status_basis: "none"
      status_post: null
      decided_by: null
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-1"
        - "ev-2"
        - "ev-3"
        - "ev-4"
        - "ev-5"
        - "ev-6"
      reasons:
        - stance: "pro"
          text: "The proposal aligns with the goal of providing a unified, high-performance profiler for Python, which is beneficial for observability and tool consistency."
          support: "unchecked"
          evidence:
            - "ev-1"
            - "ev-2"
            - "ev-3"
            - "ev-4"
            - "ev-5"
            - "ev-6"
      history:
        - post_id: "dpo:100898:264267"
          act: "accept"
          role: "author"
          author: "pablogsal"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "unresolved"
          evidence:
            - "ev-1"
            - "ev-2"
            - "ev-3"
            - "ev-4"
            - "ev-5"
            - "ev-6"
    - key: "A2"
      title: "profilers"
      summary: "The proposal maintains consistency with the `profile` module name, which is widely used and understood, and aligns with the goal"
      status: "unresolved"
      status_kind: "unresolved"
      status_basis: "none"
      status_post: null
      decided_by: null
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-1"
        - "ev-2"
        - "ev-3"
        - "ev-4"
        - "ev-5"
        - "ev-6"
      reasons:
        - stance: "pro"
          text: "The proposal maintains consistency with the `profile` module name, which is widely used and understood, and aligns with the goal of providing a unified, high-performance profiler for Python."
          support: "unchecked"
          evidence:
            - "ev-1"
            - "ev-2"
            - "ev-3"
            - "ev-4"
            - "ev-5"
            - "ev-6"
      history:
        - post_id: "dpo:100898:264267"
          act: "accept"
          role: "author"
          author: "pablogsal"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "unresolved"
          evidence:
            - "ev-1"
            - "ev-2"
            - "ev-3"
            - "ev-4"
            - "ev-5"
            - "ev-6"
    - key: "A3"
      title: "Use a dedicated profiling package"
      summary: "The proposal aims to provide a unified, high-performance profiler for Python, which is beneficial for observability and simplifies the implementation"
      status: "unresolved"
      status_kind: "unresolved"
      status_basis: "none"
      status_post: null
      decided_by: null
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-7"
      reasons:
        - stance: "pro"
          text: "The proposal aims to provide a unified, high-performance profiler for Python, which is beneficial for observability and simplifies the implementation of a new profiler."
          support: "unchecked"
          evidence:
            - "ev-7"
      history:
        - post_id: "dpo:100898:264174"
          act: "accept"
          role: "author"
          author: "pablogsal"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "unresolved"
          evidence:
            - "ev-7"
    - key: "A4"
      title: "Use the `profiling` module"
      summary: "The proposal aligns with the goal of providing a unified, high-performance profiler for Python, which is beneficial for observability and"
      status: "unresolved"
      status_kind: "unresolved"
      status_basis: "none"
      status_post: null
      decided_by: null
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-7"
      reasons:
        - stance: "pro"
          text: "The proposal aligns with the goal of providing a unified, high-performance profiler for Python, which is beneficial for observability and simplifies the implementation of a new profiler."
          support: "unchecked"
          evidence:
            - "ev-7"
        - stance: "pro"
          text: "The proposal maintains consistency with the `profile` module name, which is widely used and understood, and aligns with the goal."
          support: "unchecked"
          evidence:
            - "ev-7"
      history:
        - post_id: "dpo:100898:264174"
          act: "accept"
          role: "author"
          author: "pablogsal"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "unresolved"
          evidence:
            - "ev-7"
    - key: "A5"
      title: "Use a decorator"
      summary: "Decorators cannot wrap imports."
      status: "rejected"
      status_kind: "inferred"
      status_basis: "author_statement"
      status_post: "dpo:100898:264174"
      decided_by:
        handle: "pablogsal"
        role: "author"
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-7"
      reasons:
        - stance: "con"
          text: "Decorators cannot wrap imports."
          support: "unchecked"
          evidence:
            - "ev-7"
      history:
        - post_id: "dpo:100898:264174"
          act: "reject"
          role: "author"
          author: "pablogsal"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-7"
  evidence:
    - id: "ev-1"
      source: "dpo-100898-264174"
      kind: "discussion_post"
      post_id: "dpo:100898:264174"
      post_version: 2
      digest: "sha256:a120dfd0f96b0c57c53619130376f7150df860ab973a288a181ca68ad1ca9a54"
      sentence_indexes:
        - 2
      start: 14
      end: 194
      quote: "This is a straightforward structural proposal: PEP 799 introduces a new `profilers` standard library module to house Python’s built-in profilers under a single, coherent namespace."
      url: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/1"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-2"
      source: "dpo-100898-264197"
      kind: "discussion_post"
      post_id: "dpo:100898:264197"
      post_version: 3
      digest: "sha256:000f370f329a3fd213e0f2a2c2c11f2a6b8d4c4501740c9663287f2298684e49"
      sentence_indexes:
        - 6
      start: 1927
      end: 2058
      quote: "-   Including this in the stdlib helps steer users away from outdated tools like `profile`, and toward modern, efficient practices."
      url: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/3"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-3"
      source: "dpo-100898-264212"
      kind: "discussion_post"
      post_id: "dpo:100898:264212"
      post_version: 1
      digest: "sha256:4aee3fc1933a917db18a401b3b45988204f7bebe9e577f8513aac59806c105f0"
      sentence_indexes:
        - 2
      start: 45
      end: 111
      quote: "I agree that `profiling` is a better module name than `profilers`."
      url: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/4"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-4"
      source: "dpo-100898-264214"
      kind: "discussion_post"
      post_id: "dpo:100898:264214"
      post_version: 1
      digest: "sha256:7c7844580f02617301b514f64f0fcc0f9547154c4983e66257d28c1c14eabeaf"
      sentence_indexes:
        - 6
      start: 143
      end: 151
      quote: "0 voters"
      url: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/6"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-5"
      source: "dpo-100898-264266"
      kind: "discussion_post"
      post_id: "dpo:100898:264266"
      post_version: 1
      digest: "sha256:19344f6b764436ecd48fd265d1c5c174bd32570002ba8927802779faab704858"
      sentence_indexes:
        - 2
      start: 131
      end: 291
      quote: "Aliases can make sense when we need compatibility, but if we’re introducing something new, I’d prefer having it under only one name so users don’t get confused."
      url: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/7"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-6"
      source: "dpo-100898-264267"
      kind: "discussion_post"
      post_id: "dpo:100898:264267"
      post_version: 3
      digest: "sha256:7d4e225a77369d14f3a02b560871b644220cfad0dc3843d61eae66c9ee280670"
      sentence_indexes:
        - 2
      start: 10
      end: 216
      quote: "The idea is that we would mostly advertise the `profilers.sampling` one but I wanted to have an alias for the name the same way you would have `cProfile` (which we are not removing) and `profilers.tracing`."
      url: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/8"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-7"
      source: "dpo-100898-264174"
      kind: "discussion_post"
      post_id: "dpo:100898:264174"
      post_version: 2
      digest: "sha256:a120dfd0f96b0c57c53619130376f7150df860ab973a288a181ca68ad1ca9a54"
      sentence_indexes:
        - 1
        - 2
        - 3
      start: 0
      end: 199
      quote: "Hi everyone,\n\nThis is a straightforward structural proposal: PEP 799 introduces a new `profilers` standard library module to house Python’s built-in profilers under a single, coherent namespace.\n\nIt:"
      url: "https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/1"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
  code:
    - repo: ""
      path: "profiling/tracing.py"
      commit: null
      pr: null
      method: "mentioned"
      strength: "direct"
---

# Question

PEP 799 – A dedicated profilers package for organizing Python profiling tool

# Decision outcome

5 options: 1 rejected, 4 unresolved. Decided in post #1 by pablogsal (author).[^dpo-100898-264174]

# Considered options

| Option | Status | Kind | Confidence | Main reason |
|---|---|---|---|---|
| profiling (A1) | unresolved | unresolved | low | The proposal aligns with the goal of providing a unified, high-performance profiler for Python, which is beneficial for observability and tool consistency. |
| profilers (A2) | unresolved | unresolved | low | The proposal maintains consistency with the `profile` module name, which is widely used and understood, and aligns with the goal of providing a unified, high-performance profiler for Python. |
| Use a dedicated profiling package (A3) | unresolved | unresolved | low | The proposal aims to provide a unified, high-performance profiler for Python, which is beneficial for observability and simplifies the implementation of a new profiler. |
| Use the `profiling` module (A4) | unresolved | unresolved | low | The proposal aligns with the goal of providing a unified, high-performance profiler for Python, which is beneficial for observability and simplifies the implementation of a new profiler. |
| Use a decorator (A5) | rejected | inferred | low | Decorators cannot wrap imports. |

# Rejected ideas

## Use a decorator

Status: rejected (inferred, confidence low). Basis: author statement by pablogsal (author) in post #1.[^dpo-100898-264174]

- con: Decorators cannot wrap imports.[^dpo-100898-264174]

# Code

- `profiling/tracing.py`: mentioned, direct

# Evidence

Each quote below is the exact text `text[start:end]` of the cited sentences in one version of a post. The `decrack.evidence` list in the frontmatter holds the same quotes with their post IDs, post versions, digests, sentence indexes, offsets, source checks and support verdicts.

- > This is a straightforward structural proposal: PEP 799 introduces a new `profilers` standard library module to house Python’s built-in profilers under a single, coherent namespace. ([dpo:100898:264174 s2](https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/1))[^dpo-100898-264174]
- > \- Including this in the stdlib helps steer users away from outdated tools like `profile`, and toward modern, efficient practices. ([dpo:100898:264197 s6](https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/3))[^dpo-100898-264197]
- > I agree that `profiling` is a better module name than `profilers`. ([dpo:100898:264212 s2](https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/4))[^dpo-100898-264212]
- > 0 voters ([dpo:100898:264214 s6](https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/6))[^dpo-100898-264214]
- > Aliases can make sense when we need compatibility, but if we’re introducing something new, I’d prefer having it under only one name so users don’t get confused. ([dpo:100898:264266 s2](https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/7))[^dpo-100898-264266]
- > The idea is that we would mostly advertise the `profilers.sampling` one but I wanted to have an alias for the name the same way you would have `cProfile` (which we are not removing) and `profilers.tracing`. ([dpo:100898:264267 s2](https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/8))[^dpo-100898-264267]
- > Hi everyone, This is a straightforward structural proposal: PEP 799 introduces a new `profilers` standard library module to house Python’s built-in profilers under a single, coherent namespace. It: ([dpo:100898:264174 s1-s3](https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/1))[^dpo-100898-264174]

[^dpo-100898-264174]: Post #1 by pablogsal, https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/1
[^dpo-100898-264197]: Post #3 by pablogsal, https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/3
[^dpo-100898-264212]: Post #4 by guido, https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/4
[^dpo-100898-264214]: Post #6 by pablogsal, https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/6
[^dpo-100898-264266]: Post #7 by Jelle, https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/7
[^dpo-100898-264267]: Post #8 by pablogsal, https://discuss.python.org/t/pep-799-a-dedicated-profilers-package-for-organizing-python-profiling-tool/100898/8
