---
type: "Decision Record"
title: "PEP 806: Mixed sync/async context managers with precise async marking"
description: "4 options: 3 rejected, 1 unresolved. Question: PEP 806: Mixed sync/async context managers with precise async marking"
resource: "https://discuss.python.org/t/pep-806-mixed-sync-async-context-managers-with-precise-async-marking/103971"
tags:
  - "decrack"
  - "pep-806"
  - "rejected"
  - "unresolved"
status: "draft"
generated:
  by: "decrack/0.1.0"
  at: "2026-10-31T22:49:03Z"
sources:
  - id: "dpo-92939-250128"
    resource: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/1"
    title: "Post #1 by Zac-HD"
    author: "human:Zac-HD@discuss.python.org"
    last_modified: "2025-05-22T21:13:54Z"
  - id: "dpo-92939-250637"
    resource: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/10"
    title: "Post #10 by rrolls"
    author: "human:rrolls@discuss.python.org"
    last_modified: "2025-05-25T11:06:05Z"
  - id: "dpo-92939-250922"
    resource: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/11"
    title: "Post #11 by Zac-HD"
    author: "human:Zac-HD@discuss.python.org"
    last_modified: "2025-05-26T17:56:32Z"
  - id: "dpo-92939-250924"
    resource: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/12"
    title: "Post #12 by Zac-HD"
    author: "human:Zac-HD@discuss.python.org"
    last_modified: "2025-05-26T18:01:13Z"
decrack:
  schema: "decrack-record/0.2"
  id: "dr-5f7bb216"
  question: "PEP 806: Mixed sync/async context managers with precise async marking"
  thread_id: "pep:806"
  decided_by:
    handle: "Zac-HD"
    role: "author"
  decided_in_post: "dpo:92939:250128"
  verification: "unverified"
  model: "qwen2.5:1.5b"
  run_mode: "live"
  prompt_version: "decrack-prompts-3"
  support_checked: false
  options:
    - key: "A1"
      title: "Allow `async with` to accept both sync and async context managers in"
      summary: "This proposal allows for a cleaner and more readable code, eliminating the need for nested indentation and making it easier"
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
      reasons:
        - stance: "pro"
          text: "This proposal allows for a cleaner and more readable code, eliminating the need for nested indentation and making it easier to understand the context managers used."
          support: "unchecked"
          evidence:
            - "ev-1"
            - "ev-2"
        - stance: "pro"
          text: "The proposal allows for a cleaner and more readable code, eliminating the need for nested indentation and making it easier to maintain and understand."
          support: "unchecked"
          evidence:
            - "ev-1"
      history:
        - post_id: "dpo:92939:250128"
          act: "accept"
          role: "author"
          author: "Zac-HD"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "unresolved"
          evidence:
            - "ev-1"
            - "ev-2"
    - key: "A2"
      title: "Use `async with` when someone uses it for a sync manager,"
      summary: "This solution ensures that the correct context managers are used and makes the code more explicit, avoiding potential issues with"
      status: "rejected"
      status_kind: "contested"
      status_basis: "author_statement"
      status_post: "dpo:92939:250128"
      decided_by:
        handle: "Zac-HD"
        role: "author"
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-1"
        - "ev-3"
        - "ev-4"
      reasons:
        - stance: "con"
          text: "This solution ensures that the correct context managers are used and makes the code more explicit, avoiding potential issues with the current nested indentation."
          support: "unchecked"
          evidence:
            - "ev-1"
        - stance: "pro"
          text: "This solution ensures that the correct context managers are used and makes the code more explicit, avoiding potential issues with deadlocks and task switching."
          support: "unchecked"
          evidence:
            - "ev-3"
            - "ev-4"
      history:
        - post_id: "dpo:92939:250128"
          act: "reject"
          role: "author"
          author: "Zac-HD"
          evidence_type: "decision_statement"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-1"
        - post_id: "dpo:92939:250924"
          act: "accept"
          role: "author"
          author: "Zac-HD"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-3"
            - "ev-4"
    - key: "A3"
      title: "Move `async` keyword inside the parens,"
      summary: "This change makes the code more readable and explicit, allowing for a clearer distinction between sync and async context managers."
      status: "rejected"
      status_kind: "confirmed"
      status_basis: "author_statement"
      status_post: "dpo:92939:250128"
      decided_by:
        handle: "Zac-HD"
        role: "author"
      status_note: ""
      confidence: "high"
      evidence:
        - "ev-1"
        - "ev-5"
      reasons:
        - stance: "con"
          text: "This change makes the code more readable and explicit, allowing for a clearer distinction between sync and async context managers, but it does not address the issue of nested indentation."
          support: "unchecked"
          evidence:
            - "ev-1"
        - stance: "con"
          text: "The proposal makes the code more readable and explicit, allowing for a clearer distinction between sync and async context managers."
          support: "unchecked"
          evidence:
            - "ev-1"
        - stance: "pro"
          text: "This change makes the code more readable and explicit, allowing for a clearer distinction between sync and async context managers."
          support: "unchecked"
          evidence:
            - "ev-5"
      history:
        - post_id: "dpo:92939:250128"
          act: "reject"
          role: "author"
          author: "Zac-HD"
          evidence_type: "decision_statement"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-1"
        - post_id: "dpo:92939:250637"
          act: "accept"
          role: "participant"
          author: "rrolls"
          evidence_type: "support"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-5"
    - key: "A4"
      title: "Allow `with async foo as bar` as an equivalent to `async with"
      summary: "This solution maintains the syntactic visibility of context managers and avoids the need for additional checks, making the code more"
      status: "rejected"
      status_kind: "contested"
      status_basis: "author_statement"
      status_post: "dpo:92939:250128"
      decided_by:
        handle: "Zac-HD"
        role: "author"
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-1"
        - "ev-6"
        - "ev-3"
      reasons:
        - stance: "con"
          text: "This solution maintains the syntactic visibility of context managers and avoids the need for additional checks, making the code more readable and explicit, but it does not address the issue of nested indentation."
          support: "unchecked"
          evidence:
            - "ev-1"
        - stance: "con"
          text: "The proposal maintains the syntactic visibility of context managers and avoids the need for additional checks, making the code more readable and maintainable."
          support: "unchecked"
          evidence:
            - "ev-1"
        - stance: "pro"
          text: "This solution maintains the syntactic visibility of context managers and avoids the need for additional checks, making the code more understandable and maintainable."
          support: "unchecked"
          evidence:
            - "ev-6"
            - "ev-3"
      history:
        - post_id: "dpo:92939:250128"
          act: "reject"
          role: "author"
          author: "Zac-HD"
          evidence_type: "decision_statement"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-1"
        - post_id: "dpo:92939:250922"
          act: "accept"
          role: "author"
          author: "Zac-HD"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-6"
            - "ev-3"
  evidence:
    - id: "ev-1"
      source: "dpo-92939-250128"
      kind: "discussion_post"
      post_id: "dpo:92939:250128"
      post_version: 1
      digest: "sha256:97e279a6fb60929697ce11b4d1bc59705be2689a4d1e186fc34594325d806c76"
      sentence_indexes:
        - 1
        - 2
        - 3
      start: 0
      end: 278
      quote: "TL;DR: Let’s allow `async with` to accept both sync and async context managers in a single statement, as long as there’s at least one async context manager present. This would eliminate the nested indentation that currently plagues mixed context manager code. GitHub issue here."
      url: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/1"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "decision_statement"
    - id: "ev-2"
      source: "dpo-92939-250128"
      kind: "discussion_post"
      post_id: "dpo:92939:250128"
      post_version: 1
      digest: "sha256:97e279a6fb60929697ce11b4d1bc59705be2689a4d1e186fc34594325d806c76"
      sentence_indexes:
        - 2
        - 3
      start: 165
      end: 278
      quote: "This would eliminate the nested indentation that currently plagues mixed context manager code. GitHub issue here."
      url: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/1"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-3"
      source: "dpo-92939-250922"
      kind: "discussion_post"
      post_id: "dpo:92939:250922"
      post_version: 1
      digest: "sha256:dbf9a385dbcecf4870c6bc425c5bd1484ddab2851fce917b957177977673b288"
      sentence_indexes:
        - 2
      start: 158
      end: 384
      quote: "Trio goes to considerable lengths to ensure that every time you see the `await`, `async for`, or `async with` keyword, it’s executing a checkpoint where the event loop has a chance to cancel the task or schedule other work[1]."
      url: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/11"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-4"
      source: "dpo-92939-250924"
      kind: "discussion_post"
      post_id: "dpo:92939:250924"
      post_version: 1
      digest: "sha256:b1ef3a249b1f31838d78c2ff5d902f6ea433ff48c930e95ec6c20e721eb3eacd"
      sentence_indexes:
        - 1
      start: 0
      end: 105
      quote: "This seems like an elegant and explicit solution to me, although as new syntax it’s also a larger change."
      url: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/12"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-5"
      source: "dpo-92939-250637"
      kind: "discussion_post"
      post_id: "dpo:92939:250637"
      post_version: 1
      digest: "sha256:a4b3db4f6d315b48eb44b301fd8afb7c7752b13e6e78d58d66661ee9d4d001aa"
      sentence_indexes:
        - 2
        - 3
      start: 62
      end: 578
      quote: "```\nwith (\n    async acquire_lock() as lock,\n    open('config.json') as f,\n    async connect_to_db() as db,\n    temp_directory() as tmpdir,\n):\n\n```\n\nNow you can mix sync and async context managers in a single `with` block, and, unlike with the OP’s solution as-is, it’s abundantly clear to anyone reading the code which context managers are async and which aren’t, and the interpreter doesn’t have to waste any time checking, either - it can raise `RuntimeError` if any of the context managers are of the wrong kind."
      url: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/10"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "support"
    - id: "ev-6"
      source: "dpo-92939-250637"
      kind: "discussion_post"
      post_id: "dpo:92939:250637"
      post_version: 1
      digest: "sha256:a4b3db4f6d315b48eb44b301fd8afb7c7752b13e6e78d58d66661ee9d4d001aa"
      sentence_indexes:
        - 4
      start: 580
      end: 792
      quote: "For completeness, I suppose we should probably also allow `with async foo as bar` as an equivalent to `async with foo as bar` (for the case where you’re only entering one context manager and not a bunch of them)."
      url: "https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/10"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
  code: []
---

# Question

PEP 806: Mixed sync/async context managers with precise async marking

# Decision outcome

4 options: 3 rejected, 1 unresolved. Decided in post #1 by Zac-HD (author).[^dpo-92939-250128]

# Considered options

| Option | Status | Kind | Confidence | Main reason |
|---|---|---|---|---|
| Allow `async with` to accept both sync and async context managers in (A1) | unresolved | unresolved | low | This proposal allows for a cleaner and more readable code, eliminating the need for nested indentation and making it easier to understand the context managers used. |
| Use `async with` when someone uses it for a sync manager, (A2) | rejected | contested | low | This solution ensures that the correct context managers are used and makes the code more explicit, avoiding potential issues with the current nested indentation. |
| Move `async` keyword inside the parens, (A3) | rejected | confirmed | high | This change makes the code more readable and explicit, allowing for a clearer distinction between sync and async context managers, but it does not address the issue of nested indentation. |
| Allow `with async foo as bar` as an equivalent to `async with (A4) | rejected | contested | low | This solution maintains the syntactic visibility of context managers and avoids the need for additional checks, making the code more readable and explicit, but it does not address the issue of nested indentation. |

# Rejected ideas

## Use `async with` when someone uses it for a sync manager,

Status: rejected (contested, confidence low). Basis: author statement by Zac-HD (author) in post #1.[^dpo-92939-250128]

- con: This solution ensures that the correct context managers are used and makes the code more explicit, avoiding potential issues with the current nested indentation.[^dpo-92939-250128]
- pro: This solution ensures that the correct context managers are used and makes the code more explicit, avoiding potential issues with deadlocks and task switching.[^dpo-92939-250922][^dpo-92939-250924]

## Move `async` keyword inside the parens,

Status: rejected (confirmed, confidence high). Basis: author statement by Zac-HD (author) in post #1.[^dpo-92939-250128]

- con: This change makes the code more readable and explicit, allowing for a clearer distinction between sync and async context managers, but it does not address the issue of nested indentation.[^dpo-92939-250128]
- con: The proposal makes the code more readable and explicit, allowing for a clearer distinction between sync and async context managers.[^dpo-92939-250128]
- pro: This change makes the code more readable and explicit, allowing for a clearer distinction between sync and async context managers.[^dpo-92939-250637]

## Allow `with async foo as bar` as an equivalent to `async with

Status: rejected (contested, confidence low). Basis: author statement by Zac-HD (author) in post #1.[^dpo-92939-250128]

- con: This solution maintains the syntactic visibility of context managers and avoids the need for additional checks, making the code more readable and explicit, but it does not address the issue of nested indentation.[^dpo-92939-250128]
- con: The proposal maintains the syntactic visibility of context managers and avoids the need for additional checks, making the code more readable and maintainable.[^dpo-92939-250128]
- pro: This solution maintains the syntactic visibility of context managers and avoids the need for additional checks, making the code more understandable and maintainable.[^dpo-92939-250637][^dpo-92939-250922]

# Code

No code links recorded.

# Evidence

Each quote below is the exact text `text[start:end]` of the cited sentences in one version of a post. The `decrack.evidence` list in the frontmatter holds the same quotes with their post IDs, post versions, digests, sentence indexes, offsets, source checks and support verdicts.

- > TL;DR: Let’s allow `async with` to accept both sync and async context managers in a single statement, as long as there’s at least one async context manager present. This would eliminate the nested indentation that currently plagues mixed context manager code. GitHub issue here. ([dpo:92939:250128 s1-s3](https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/1))[^dpo-92939-250128]
- > This would eliminate the nested indentation that currently plagues mixed context manager code. GitHub issue here. ([dpo:92939:250128 s2-s3](https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/1))[^dpo-92939-250128]
- > Trio goes to considerable lengths to ensure that every time you see the `await`, `async for`, or `async with` keyword, it’s executing a checkpoint where the event loop has a chance to cancel the task or schedule other work[1]. ([dpo:92939:250922 s2](https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/11))[^dpo-92939-250922]
- > This seems like an elegant and explicit solution to me, although as new syntax it’s also a larger change. ([dpo:92939:250924 s1](https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/12))[^dpo-92939-250924]
- > ``` with ( async acquire_lock() as lock, open('config.json') as f, async connect_to_db() as db, temp_directory() as tmpdir, ): ``` Now you can mix sync and async context managers in a single `with` block, and, unlike with the OP’s solution as-is, it’s abundantly clear to anyone reading the code which context managers are async and which aren’t, and the interpreter doesn’t have to waste any time checking, either - it can raise `RuntimeError` if any of the context managers are of the wrong kind. ([dpo:92939:250637 s2-s3](https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/10))[^dpo-92939-250637]
- > For completeness, I suppose we should probably also allow `with async foo as bar` as an equivalent to `async with foo as bar` (for the case where you’re only entering one context manager and not a bunch of them). ([dpo:92939:250637 s4](https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/10))[^dpo-92939-250637]

[^dpo-92939-250128]: Post #1 by Zac-HD, https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/1
[^dpo-92939-250637]: Post #10 by rrolls, https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/10
[^dpo-92939-250922]: Post #11 by Zac-HD, https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/11
[^dpo-92939-250924]: Post #12 by Zac-HD, https://discuss.python.org/t/allow-mixed-sync-async-context-managers-in-async-with-statements/92939/12
