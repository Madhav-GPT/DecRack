---
type: "Decision Record"
title: "PEP 830: Add timestamps to exceptions and tracebacks"
description: "4 options: 3 rejected, 1 unresolved. Question: PEP 830: Add timestamps to exceptions and tracebacks"
resource: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942"
tags:
  - "decrack"
  - "pep-830"
  - "rejected"
  - "unresolved"
status: "draft"
generated:
  by: "decrack/0.1.0"
  at: "2026-10-31T22:46:57Z"
sources:
  - id: "dpo-106942-290074"
    resource: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1"
    title: "Post #1 by gpshead"
    author: "human:gpshead@discuss.python.org"
    last_modified: "2026-04-12T20:36:43Z"
  - id: "dpo-106942-290143"
    resource: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/16"
    title: "Post #16 by gpshead"
    author: "human:gpshead@discuss.python.org"
    last_modified: "2026-04-13T16:11:00Z"
  - id: "dpo-106942-290148"
    resource: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/17"
    title: "Post #17 by vstinner"
    author: "human:vstinner@discuss.python.org"
    last_modified: "2026-04-13T16:31:06Z"
  - id: "dpo-106942-290526"
    resource: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/25"
    title: "Post #25 by gpshead"
    author: "human:gpshead@discuss.python.org"
    last_modified: "2026-04-16T17:36:50Z"
decrack:
  schema: "decrack-record/0.2"
  id: "dr-8cbfcc21"
  question: "PEP 830: Add timestamps to exceptions and tracebacks"
  thread_id: "pep:830"
  decided_by:
    handle: "gpshead"
    role: "author"
  decided_in_post: "dpo:106942:290526"
  verification: "unverified"
  model: "qwen2.5:1.5b"
  run_mode: "live"
  prompt_version: "decrack-prompts-3"
  support_checked: false
  options:
    - key: "A1"
      title: "Add a timestamp to exceptions and tracebacks at the time of instantiation."
      summary: "This aligns with the current handling of exceptions and tracebacks and avoids unnecessary complexity."
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
      reasons:
        - stance: "pro"
          text: "This aligns with the current handling of exceptions and tracebacks and avoids unnecessary complexity."
          support: "unchecked"
          evidence:
            - "ev-1"
            - "ev-2"
            - "ev-3"
        - stance: "con"
          text: "This would require storing timestamps at every point a raise happens, which is not necessary and introduces unnecessary complexity."
          support: "unchecked"
          evidence:
            - "ev-2"
      history:
        - post_id: "dpo:106942:290074"
          act: "accept"
          role: "author"
          author: "gpshead"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "unresolved"
          evidence:
            - "ev-2"
        - post_id: "dpo:106942:290074"
          act: "reject"
          role: "author"
          author: "gpshead"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-2"
        - post_id: "dpo:106942:290143"
          act: "accept"
          role: "author"
          author: "gpshead"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "unresolved"
          evidence:
            - "ev-1"
            - "ev-3"
    - key: "A2"
      title: "Use `sys.excepthook` to add a timestamp to exceptions."
      summary: "It does not get called at the time of raise or construction, which would defeat the purpose for this use"
      status: "rejected"
      status_kind: "inferred"
      status_basis: "author_statement"
      status_post: "dpo:106942:290074"
      decided_by:
        handle: "gpshead"
        role: "author"
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-4"
        - "ev-5"
      reasons:
        - stance: "con"
          text: "It does not get called at the time of raise or construction, which would defeat the purpose for this use."
          support: "unchecked"
          evidence:
            - "ev-4"
        - stance: "con"
          text: "It does not get called at the time of raise or construction, which would defeat the purpose for this use case of having every exception raised in an ExceptionGroup carry a timestamp at the point it occurred."
          support: "unchecked"
          evidence:
            - "ev-5"
        - stance: "con"
          text: "It has a resolution of 1 microsecond, which is not sufficient for exception timestamps."
          support: "unchecked"
          evidence:
            - "ev-5"
      history:
        - post_id: "dpo:106942:290074"
          act: "reject"
          role: "author"
          author: "gpshead"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-4"
        - post_id: "dpo:106942:290148"
          act: "reject"
          role: "maintainer"
          author: "vstinner"
          evidence_type: "objection"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-5"
    - key: "A3"
      title: "Use `traceback.strip_exc_timestamps()` to remove timestamps from exceptions."
      summary: "It impacts application performance, including pathological cases."
      status: "rejected"
      status_kind: "inferred"
      status_basis: "author_statement"
      status_post: "dpo:106942:290526"
      decided_by:
        handle: "gpshead"
        role: "author"
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-6"
        - "ev-7"
      reasons:
        - stance: "con"
          text: "It impacts application performance, including pathological cases."
          support: "unchecked"
          evidence:
            - "ev-6"
            - "ev-7"
      history:
        - post_id: "dpo:106942:290074"
          act: "reject"
          role: "author"
          author: "gpshead"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-6"
        - post_id: "dpo:106942:290526"
          act: "reject"
          role: "author"
          author: "gpshead"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-7"
    - key: "A4"
      title: "Use `traceback.format_exception_only()` to format the exception without timestamps."
      summary: "It impacts application performance, including pathological cases."
      status: "rejected"
      status_kind: "inferred"
      status_basis: "author_statement"
      status_post: "dpo:106942:290526"
      decided_by:
        handle: "gpshead"
        role: "author"
      status_note: ""
      confidence: "low"
      evidence:
        - "ev-6"
        - "ev-7"
      reasons:
        - stance: "con"
          text: "It impacts application performance, including pathological cases."
          support: "unchecked"
          evidence:
            - "ev-6"
            - "ev-7"
      history:
        - post_id: "dpo:106942:290074"
          act: "reject"
          role: "author"
          author: "gpshead"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-6"
        - post_id: "dpo:106942:290526"
          act: "reject"
          role: "author"
          author: "gpshead"
          evidence_type: "author_position"
          support: "unchecked"
          status_after: "rejected"
          evidence:
            - "ev-7"
  evidence:
    - id: "ev-1"
      source: "dpo-106942-290074"
      kind: "discussion_post"
      post_id: "dpo:106942:290074"
      post_version: 1
      digest: "sha256:25719f1f45e2cd897fd2cc0c87b19901f9cbfdcfd2de95afc09638ce64ebe155"
      sentence_indexes:
        - 1
      start: 0
      end: 131
      quote: "This PEP adds an optional timestamp to all exceptions that records when the exception was instantiated with no observable overhead."
      url: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-2"
      source: "dpo-106942-290074"
      kind: "discussion_post"
      post_id: "dpo:106942:290074"
      post_version: 1
      digest: "sha256:25719f1f45e2cd897fd2cc0c87b19901f9cbfdcfd2de95afc09638ce64ebe155"
      sentence_indexes:
        - 1
        - 2
        - 3
      start: 0
      end: 443
      quote: "This PEP adds an optional timestamp to all exceptions that records when the exception was instantiated with no observable overhead. When enabled via environment variable or command-line flag, formatted tracebacks display this timestamp alongside the exception message.\n\nIf you’ve ever debugged a production Python system involving many forms of concurrency and wished you had more information about what happened when, this PEP may be for you."
      url: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-3"
      source: "dpo-106942-290143"
      kind: "discussion_post"
      post_id: "dpo:106942:290143"
      post_version: 1
      digest: "sha256:56168e8ba47ac9cbcfedad01b0af992a2ba411a42deed8c3dab87956abc91f5c"
      sentence_indexes:
        - 1
      start: 0
      end: 151
      quote: "Okay so I gather this is what you were talking about in regards to the bare `raise` that reraises the currently being handled exception as one example."
      url: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/16"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-4"
      source: "dpo-106942-290074"
      kind: "discussion_post"
      post_id: "dpo:106942:290074"
      post_version: 1
      digest: "sha256:25719f1f45e2cd897fd2cc0c87b19901f9cbfdcfd2de95afc09638ce64ebe155"
      sentence_indexes:
        - 2
      start: 132
      end: 268
      quote: "When enabled via environment variable or command-line flag, formatted tracebacks display this timestamp alongside the exception message."
      url: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-5"
      source: "dpo-106942-290148"
      kind: "discussion_post"
      post_id: "dpo:106942:290148"
      post_version: 1
      digest: "sha256:0a6eec3b775ef7c96caf179cad429e593cde752f0476d5e7822125f17d469d62"
      sentence_indexes:
        - 1
        - 2
      start: 0
      end: 190
      quote: "I think that this idea (adding a timestamp to exceptions) was already discussed previously, but I failed to find the link. Or maybe it was your PR gh-129337 that you created in January 2025."
      url: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/17"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "objection"
    - id: "ev-6"
      source: "dpo-106942-290074"
      kind: "discussion_post"
      post_id: "dpo:106942:290074"
      post_version: 1
      digest: "sha256:25719f1f45e2cd897fd2cc0c87b19901f9cbfdcfd2de95afc09638ce64ebe155"
      sentence_indexes:
        - 3
      start: 270
      end: 443
      quote: "If you’ve ever debugged a production Python system involving many forms of concurrency and wished you had more information about what happened when, this PEP may be for you."
      url: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
    - id: "ev-7"
      source: "dpo-106942-290526"
      kind: "discussion_post"
      post_id: "dpo:106942:290526"
      post_version: 1
      digest: "sha256:dff867a65fe5e6b02e8daf8b86478b8b50595f2e9f9f35f4ad8e769cf1ea84f8"
      sentence_indexes:
        - 1
        - 2
      start: 0
      end: 110
      quote: "Yes `sys.monitoring` could be used to do this today. But that is a heavyweight call and very heavyweight note."
      url: "https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/25"
      source_check: "valid"
      support: "unchecked"
      evidence_type: "author_position"
  code:
    - repo: ""
      path: "Python/errors.c"
      commit: null
      pr: null
      method: "mentioned"
      strength: "direct"
    - repo: ""
      path: "cpython/Objects/exceptions.c"
      commit: null
      pr: null
      method: "mentioned"
      strength: "direct"
---

# Question

PEP 830: Add timestamps to exceptions and tracebacks

# Decision outcome

4 options: 3 rejected, 1 unresolved. Decided in post #25 by gpshead (author).[^dpo-106942-290526]

# Considered options

| Option | Status | Kind | Confidence | Main reason |
|---|---|---|---|---|
| Add a timestamp to exceptions and tracebacks at the time of instantiation. (A1) | unresolved | unresolved | low | This aligns with the current handling of exceptions and tracebacks and avoids unnecessary complexity. |
| Use `sys.excepthook` to add a timestamp to exceptions. (A2) | rejected | inferred | low | It does not get called at the time of raise or construction, which would defeat the purpose for this use. |
| Use `traceback.strip_exc_timestamps()` to remove timestamps from exceptions. (A3) | rejected | inferred | low | It impacts application performance, including pathological cases. |
| Use `traceback.format_exception_only()` to format the exception without timestamps. (A4) | rejected | inferred | low | It impacts application performance, including pathological cases. |

# Rejected ideas

## Use `sys.excepthook` to add a timestamp to exceptions.

Status: rejected (inferred, confidence low). Basis: author statement by gpshead (author) in post #1.[^dpo-106942-290074]

- con: It does not get called at the time of raise or construction, which would defeat the purpose for this use.[^dpo-106942-290074]
- con: It does not get called at the time of raise or construction, which would defeat the purpose for this use case of having every exception raised in an ExceptionGroup carry a timestamp at the point it occurred.[^dpo-106942-290148]
- con: It has a resolution of 1 microsecond, which is not sufficient for exception timestamps.[^dpo-106942-290148]

## Use `traceback.strip_exc_timestamps()` to remove timestamps from exceptions.

Status: rejected (inferred, confidence low). Basis: author statement by gpshead (author) in post #25.[^dpo-106942-290526]

- con: It impacts application performance, including pathological cases.[^dpo-106942-290074][^dpo-106942-290526]

## Use `traceback.format_exception_only()` to format the exception without timestamps.

Status: rejected (inferred, confidence low). Basis: author statement by gpshead (author) in post #25.[^dpo-106942-290526]

- con: It impacts application performance, including pathological cases.[^dpo-106942-290074][^dpo-106942-290526]

# Code

- `Python/errors.c`: mentioned, direct
- `cpython/Objects/exceptions.c`: mentioned, direct

# Evidence

Each quote below is the exact text `text[start:end]` of the cited sentences in one version of a post. The `decrack.evidence` list in the frontmatter holds the same quotes with their post IDs, post versions, digests, sentence indexes, offsets, source checks and support verdicts.

- > This PEP adds an optional timestamp to all exceptions that records when the exception was instantiated with no observable overhead. ([dpo:106942:290074 s1](https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1))[^dpo-106942-290074]
- > This PEP adds an optional timestamp to all exceptions that records when the exception was instantiated with no observable overhead. When enabled via environment variable or command-line flag, formatted tracebacks display this timestamp alongside the exception message. If you’ve ever debugged a production Python system involving many forms of concurrency and wished you had more information about what happened when, this PEP may be for you. ([dpo:106942:290074 s1-s3](https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1))[^dpo-106942-290074]
- > Okay so I gather this is what you were talking about in regards to the bare `raise` that reraises the currently being handled exception as one example. ([dpo:106942:290143 s1](https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/16))[^dpo-106942-290143]
- > When enabled via environment variable or command-line flag, formatted tracebacks display this timestamp alongside the exception message. ([dpo:106942:290074 s2](https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1))[^dpo-106942-290074]
- > I think that this idea (adding a timestamp to exceptions) was already discussed previously, but I failed to find the link. Or maybe it was your PR gh-129337 that you created in January 2025. ([dpo:106942:290148 s1-s2](https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/17))[^dpo-106942-290148]
- > If you’ve ever debugged a production Python system involving many forms of concurrency and wished you had more information about what happened when, this PEP may be for you. ([dpo:106942:290074 s3](https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1))[^dpo-106942-290074]
- > Yes `sys.monitoring` could be used to do this today. But that is a heavyweight call and very heavyweight note. ([dpo:106942:290526 s1-s2](https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/25))[^dpo-106942-290526]

[^dpo-106942-290074]: Post #1 by gpshead, https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/1
[^dpo-106942-290143]: Post #16 by gpshead, https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/16
[^dpo-106942-290148]: Post #17 by vstinner, https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/17
[^dpo-106942-290526]: Post #25 by gpshead, https://discuss.python.org/t/pep-830-add-timestamps-to-exceptions-and-tracebacks/106942/25
