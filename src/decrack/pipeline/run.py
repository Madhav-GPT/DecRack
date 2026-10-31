"""compile_thread: the whole Compile stage for one thread.

roles -> windows -> per window: MAP, gate (against that prompt's aliases) and
keys -> consolidate (deterministic merge, events, reasons, evidence, a
preliminary status) -> support check (only when ``support_check`` is on) ->
status rules -> code links -> DecisionRecord. By default MAP is the only model
step.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from decrack import __version__
from decrack.config import Settings
from decrack.linking import mentioned_links, pr_file_links
from decrack.models import (
    SCHEMA_VERSION,
    AliasTarget,
    CodeLink,
    DecidedBy,
    DecisionRecord,
    Evidence,
    Option,
    Post,
    RunInfo,
    SourceRef,
    Thread,
    make_record_id,
)
from decrack.pipeline.consolidate import AltRegistry, consolidate, decide, summarize_outcome
from decrack.pipeline.extract import map_window, prepare_map
from decrack.pipeline.gate import GatedCandidate, build_aliases, gate_candidates
from decrack.pipeline.llm import LLM, LLMOutputError
from decrack.pipeline.prompts import PROMPT_VERSION, opening_part
from decrack.pipeline.roles import assign_roles
from decrack.pipeline.support import check_support
from decrack.pipeline.windows import make_windows


def compile_thread(
    thread: Thread,
    llm: LLM,
    settings: Settings,
    progress: Callable[[str], None] | None = None,
) -> DecisionRecord:
    """Compile ``thread`` into a DecisionRecord.

    Only ``LLMOutputError`` is caught (per window here; per support batch in
    ``check_support``), so one bad answer costs one window; any other model
    error stops the run.
    """
    started_at = datetime.now(timezone.utc)
    clock = time.monotonic()
    before = usage(llm)

    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    assign_roles(thread)
    windows = make_windows(thread, settings.window_max_tokens, settings.window_overlap_tokens)
    report(f"{thread.id}: {len(thread.posts)} posts in {len(windows)} windows")
    info = runtime_info(llm)
    header = opening_part(thread)

    registry = AltRegistry()
    gated: list[GatedCandidate] = []
    candidates_total = 0
    alias_map: dict[str, AliasTarget] = {}
    allowlist: dict[tuple[str, int, str], SourceRef] = {}
    chain = ""
    for window in windows:
        seqs = [part.post.seq for part in window.parts]
        label = f"Window {window.index + 1}/{len(windows)} (posts {seqs[0]}-{seqs[-1]})"
        aliases = build_aliases(([header] if header else []) + list(window.parts))
        for alias, (post, index) in aliases.items():
            alias_map[alias] = AliasTarget(post_id=post.id, version=post.version, index=index)
            if (post.id, post.version, post.sha256) not in allowlist:
                allowlist[(post.id, post.version, post.sha256)] = source_ref(post)
        request = prepare_map(thread, window, registry.known(), chain=chain, digest=info["model_digest"])
        chain = request.key  # the next window's key follows this window's input, answered or not
        try:
            candidates = map_window(llm, request)
        except LLMOutputError as exc:
            report(f"{label}: skipped, the model output stayed invalid: {exc}")
            continue
        result = gate_candidates(thread, candidates, aliases)
        candidates_total += result.total
        for item in result.kept:
            registry.assign(item)
        gated.extend(result.kept)
        report(f"{label}: {len(result.kept)} of {result.total} items have valid citations")

    options = consolidate(thread, gated)
    if settings.support_check:
        report("Checking that the cited sentences support each claim")
        check_support(llm, options, batch_size=settings.support_batch_size)
    for option in options:
        decide(option)

    after = usage(llm)
    decided_by, decided_in_post = decision_point(thread, options)
    record = DecisionRecord(
        id=make_record_id(thread.id),
        thread_id=thread.id,
        thread_url=thread.url,
        question=thread.title,
        outcome=summarize_outcome(options),
        options=options,
        decided_by=decided_by,
        decided_in_post=decided_in_post,
        code_links=code_links(thread),
        verification=verification(options, settings.support_check),
        run=RunInfo(
            mode=llm.mode,
            decrack_version=__version__,
            model=llm.model,
            model_digest=info["model_digest"],
            ollama_version=info["ollama_version"],
            params={
                "num_ctx": settings.num_ctx,
                "temperature": 0,
                "think": False,
                "window_max_tokens": settings.window_max_tokens,
                "window_overlap_tokens": settings.window_overlap_tokens,
                "support_check": settings.support_check,
            },
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            started_at=started_at,
            seconds=round(time.monotonic() - clock, 3),
            llm_calls=after[0] - before[0],
            cache_hits=after[1] - before[1],
            tokens_in=after[2] - before[2],
            tokens_out=after[3] - before[3],
            windows=len(windows),
            candidates_total=candidates_total,
            candidates_verified=len(gated),
            support_checked=settings.support_check,
            alias_map=alias_map,
            source_allowlist=list(allowlist.values()),
        ),
    )
    report(f"{record.id}: {record.outcome}")
    return record


def usage(llm: LLM) -> tuple[int, int, int, int]:
    """The LLM's running counters: calls, cache hits, tokens in, tokens out."""
    return llm.calls, llm.cache_hits, llm.tokens_in, llm.tokens_out


def runtime_info(llm: LLM) -> dict[str, str]:
    """Model digest and Ollama version when the LLM can tell (a live Ollama client), else empty strings."""
    ask = getattr(llm, "runtime_info", None)
    info = ask() if callable(ask) else {}
    return {
        "model_digest": str(info.get("model_digest") or ""),
        "ollama_version": str(info.get("ollama_version") or ""),
    }


def source_ref(post: Post) -> SourceRef:
    return SourceRef(post_id=post.id, version=post.version, sha256=post.sha256)


def code_links(thread: Thread) -> list[CodeLink]:
    """Paths mentioned in posts and files changed by the PR, without repeats of (repo, path, method)."""
    links: list[CodeLink] = []
    seen: set[tuple[str, str, str]] = set()
    for link in mentioned_links(thread) + pr_file_links(thread):
        mark = (link.repo, link.path, link.method)
        if mark not in seen:
            seen.add(mark)
            links.append(link)
    return links


def decision_point(thread: Thread, options: list[Option]) -> tuple[DecidedBy | None, str | None]:
    """Who decided, and in which post: the latest status post among decider-based options, else author-based ones.

    Contested options are left out, since their statements disagree.
    """
    order = {post.id: post.seq for post in thread.posts}
    for basis in ("decider_statement", "author_statement"):
        found = [
            option
            for option in options
            if option.status_basis == basis and option.status_post and option.status_kind != "contested"
        ]
        if found:
            latest = max(found, key=lambda option: order.get(option.status_post, 0))
            return latest.decided_by, latest.status_post
    return None, None


def all_evidence(option: Option) -> list[Evidence]:
    """The option's evidence plus that of its reasons and status events."""
    evidence = list(option.evidence)
    evidence += [item for reason in option.reasons for item in reason.evidence]
    evidence += [item for event in option.status_history for item in event.evidence]
    return evidence


def verification(options: list[Option], support_checked: bool) -> str:
    """"machine_checked" when support ran, there are options, each has evidence and all of it is source-valid."""
    if not support_checked or not options or not all(option.evidence for option in options):
        return "unverified"
    if all(item.source_check == "valid" for option in options for item in all_evidence(option)):
        return "machine_checked"
    return "unverified"
