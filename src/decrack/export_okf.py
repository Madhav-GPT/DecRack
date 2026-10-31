"""Export decision records as an Open Knowledge Format (OKF) v0.2 markdown bundle.

The bundle is pinned to OKF spec commit ad30107c and follows DecRack's record
template: ``index.md`` (its frontmatter holds only ``okf_version``),
``decisions/index.md``, one ``decisions/dr-xxxxxxxx-<slug>.md`` per record and
``log.md``. OKF's own frontmatter fields carry the title, provenance, footnote
sources and verification; everything decision-specific sits under one
namespaced ``decrack:`` key (schema ``decrack-record/0.2``). There, each
evidence entry names its stable post id, post version and content digest, the
sentence indexes and character offsets, and the exact quote, with its source
check, support verdict and evidence type. The body is MADR style. A record has
no expiry date: an old decision is no less valid for being old.

No YAML library is used: a small emitter writes block mappings and block
sequences, and every string goes through ``json.dumps``, which is a valid YAML
double-quoted scalar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from decrack import __version__
from decrack.models import SCHEMA_VERSION, STATUSES, DecidedBy, DecisionRecord, Evidence, Option, Thread
from decrack.text import slugify

OKF_VERSION = "0.2"
OKF_SPEC_COMMIT = "ad30107c"
RECORD_SCHEMA = SCHEMA_VERSION  # "decrack-record/0.2"
QUOTE_CHECKER = "process:decrack-quote-check"
REJECTED_STATUSES = ("rejected", "withdrawn", "deferred", "superseded")
VERIFIED_STATES = ("machine_checked", "human_confirmed")
THREAD_PREFIX_KINDS = {"dpo": "discourse", "pep": "discourse", "gh": "github", "file": "file"}
BASIS_TEXT = {
    "decider_statement": "decider statement",
    "author_statement": "author statement",
    "participant_consensus": "participant consensus",
}

# YAML ---------------------------------------------------------------------------

_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# json.dumps leaves these raw, but YAML reads them as line breaks or rejects them.
_YAML_UNSAFE = re.compile(r"[\x7f-\x9f  \ud800-\udfff￾￿]")


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    text = json.dumps(str(value), ensure_ascii=False)
    return _YAML_UNSAFE.sub(lambda match: f"\\u{ord(match.group()):04x}", text)


def _yaml_key(key: str) -> str:
    return key if _PLAIN_KEY.match(key) else _yaml_scalar(key)


def _is_block(value: Any) -> bool:
    return isinstance(value, (dict, list, tuple)) and len(value) > 0


def _yaml_flow(value: Any) -> str:
    """A value written on its key's line: a scalar, ``{}`` or ``[]``."""
    if isinstance(value, dict):
        return "{}"
    if isinstance(value, (list, tuple)):
        return "[]"
    return _yaml_scalar(value)


def _yaml_lines(value: dict | list | tuple, indent: int = 0) -> list[str]:
    """Block-style YAML lines for a non-empty mapping or sequence."""
    pad = " " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_block(item):
                lines.append(f"{pad}{_yaml_key(key)}:")
                lines.extend(_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}{_yaml_key(key)}: {_yaml_flow(item)}")
        return lines
    for item in value:
        if isinstance(item, dict) and item:
            nested = _yaml_lines(item, indent + 2)
            lines.append(f"{pad}- {nested[0].lstrip()}")
            lines.extend(nested[1:])
        elif _is_block(item):
            lines.append(f"{pad}-")
            lines.extend(_yaml_lines(item, indent + 2))
        else:
            lines.append(f"{pad}- {_yaml_flow(item)}")
    return lines


def _frontmatter(data: dict) -> str:
    return "---\n" + "\n".join(_yaml_lines(data)) + "\n---\n"


# Shared helpers -----------------------------------------------------------------


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generated_at(record: DecisionRecord) -> datetime:
    """When the record was compiled; using the run start keeps re-exports byte-identical."""
    value = record.run.started_at if record.run is not None else datetime.now(timezone.utc)
    return _utc(value).replace(microsecond=0)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _sentence(text: str) -> str:
    return text if not text or text[-1] in ".!?" else text + "."


def _md(text: str) -> str:
    """Untrusted text as one markdown line that cannot start a block or a footnote reference."""
    text = _one_line(text).replace("[^", "\\[^")
    if text[:1] in ("#", ">", "-", "+", "*", "=", "|"):
        text = "\\" + text
    return text


def _cell(text: str) -> str:
    return _md(text.replace("\\", "\\\\").replace("|", "\\|"))


def _indexes(indexes: list[int]) -> str:
    """``s2`` for one cited sentence, ``s2-s4`` for a run of them."""
    if not indexes:
        return ""
    return f"s{indexes[0]}" if len(indexes) == 1 else f"s{indexes[0]}-s{indexes[-1]}"


def _cite(ev: Evidence) -> str:
    """``[dpo:99999:1005 s2](url)``: the stable post id and the cited sentences, linked."""
    label = " ".join(part for part in (ev.post_id, _indexes(ev.sentence_indexes)) if part)
    return f"[{label}]({ev.url})" if ev.url else label


def _record_evidence(record: DecisionRecord) -> list[Evidence]:
    """Every Evidence in record order: per option, its own evidence, its reasons' and its status history's."""
    found: list[Evidence] = []
    for option in record.options:
        found.extend(option.evidence)
        for reason in option.reasons:
            found.extend(reason.evidence)
        for event in option.status_history:
            found.extend(event.evidence)
    return found


def _evidence_key(ev: Evidence) -> str:
    return ev.model_dump_json()


def _unique_evidence(record: DecisionRecord) -> list[Evidence]:
    unique: dict[str, Evidence] = {}
    for ev in _record_evidence(record):
        unique.setdefault(_evidence_key(ev), ev)
    return list(unique.values())


def _thread_kind(record: DecisionRecord, thread: Thread | None) -> str:
    if thread is not None:
        return thread.kind
    prefix = record.thread_id.partition(":")[0]
    return THREAD_PREFIX_KINDS.get(prefix, prefix or "unknown")


# Sources: one per cited post, each defined once as a footnote ------------------


@dataclass
class _Source:
    id: str  # footnote label and sources id, such as "dpo-99999-1005"
    post_id: str
    url: str = ""
    number: int | None = None  # the post's number in its source (Discourse post_number); needs the thread
    author: str = ""
    created_at: datetime | None = None


def _source_label(post_id: str, taken: set[str]) -> str:
    """A footnote label made of ``[a-z0-9-]`` only, unique among ``taken``.

    ``dpo:99001:5003`` -> ``dpo-99001-5003``; ``gh:o/r#12:c34`` -> ``gh-o-r-12-c34``.
    Labels are lower case because markdown matches footnote labels case-insensitively.
    """
    base = re.sub(r"[^a-z0-9]+", "-", post_id.lower()).strip("-") or "post"
    label, suffix = base, 2
    while label in taken:
        label, suffix = f"{base}-{suffix}", suffix + 1
    taken.add(label)
    return label


def _collect_sources(record: DecisionRecord, thread: Thread | None) -> list[_Source]:
    """One source per cited post, plus the deciding post: in thread order when the thread is known,
    else in order of first citation."""
    first: dict[str, Evidence | None] = {}
    for ev in _record_evidence(record):
        first.setdefault(ev.post_id, ev)
    if record.decided_in_post:
        first.setdefault(record.decided_in_post, None)
    posts = {post.id: post for post in thread.posts} if thread is not None else {}
    cited_order = {post_id: index for index, post_id in enumerate(first)}

    def order(post_id: str) -> tuple[int, int]:
        post = posts.get(post_id)
        return (0, post.seq) if post is not None else (1, cited_order[post_id])

    sources: list[_Source] = []
    taken: set[str] = set()
    for post_id in sorted(first, key=order):
        label = _source_label(post_id, taken)
        ev = first[post_id]
        url, author = (ev.url, ev.author) if ev is not None else ("", "")
        post = posts.get(post_id)
        if post is None:
            sources.append(_Source(label, post_id, url, None, author))
            continue
        number = post.source_post_number if post.source_post_number is not None else post.seq
        sources.append(_Source(label, post_id, url or post.url, number, post.author or author, post.created_at))
    return sources


def _platform(record: DecisionRecord, thread: Thread | None) -> str:
    """The host of the thread URL (``discuss.python.org``), else the thread kind."""
    url = record.thread_url or (thread.url if thread is not None else "")
    host = urlparse(url).hostname if url else None
    return host or _thread_kind(record, thread)


def _post_name(source: _Source) -> str:
    """``#5`` when the post's number is known, else its stable id."""
    return f"#{source.number}" if source.number is not None else source.post_id


def _source_entry(source: _Source, platform: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": source.id}
    if source.url:
        entry["resource"] = source.url
    entry["title"] = f"Post {_post_name(source)}" + (f" by {source.author}" if source.author else "")
    if source.author:
        handle = "-".join(source.author.split())
        entry["author"] = f"human:{handle}@{platform}"
    if source.created_at is not None:
        entry["last_modified"] = _iso(source.created_at)
    return entry


def _footnote(source: _Source) -> str:
    text = f"Post {_post_name(source)}" + (f" by {_md(source.author)}" if source.author else "")
    return text + (f", {source.url}" if source.url else "")


def _feet(evidence: list[Evidence], by_post: dict[str, _Source]) -> str:
    labels = dict.fromkeys(by_post[ev.post_id].id for ev in evidence if ev.post_id in by_post)
    return "".join(f"[^{label}]" for label in labels)


# Frontmatter ---------------------------------------------------------------------


def _title(record: DecisionRecord) -> str:
    return _one_line(record.question) or record.id


def _description(record: DecisionRecord) -> str:
    parts = [_sentence(_one_line(record.outcome))]
    if record.question.strip():
        parts.append(f"Question: {_one_line(record.question)}")
    return " ".join(part for part in parts if part)


def _tags(record: DecisionRecord, thread: Thread | None) -> list[str]:
    prefix, _, rest = record.thread_id.partition(":")
    kind = f"pep-{int(rest)}" if prefix == "pep" and rest.isdigit() else _thread_kind(record, thread).replace("_", "-")
    present = {option.status for option in record.options}
    return ["decrack", kind] + [status for status in STATUSES if status in present]


def _decided_by(value: DecidedBy | None) -> dict[str, str] | None:
    return {"handle": value.handle, "role": value.role} if value is not None else None


def _decrack_block(record: DecisionRecord, sources: list[_Source], evidence: list[Evidence]) -> dict[str, Any]:
    by_post = {source.post_id: source for source in sources}
    ev_ids = {_evidence_key(ev): f"ev-{index}" for index, ev in enumerate(evidence, start=1)}

    def ids(items: list[Evidence]) -> list[str]:
        return list(dict.fromkeys(ev_ids[_evidence_key(ev)] for ev in items))

    options = [
        {
            "key": option.key,
            "title": option.title,
            "summary": option.summary,
            "status": option.status,
            "status_kind": option.status_kind,
            "status_basis": option.status_basis,
            "status_post": option.status_post,
            "decided_by": _decided_by(option.decided_by),
            "status_note": option.status_note,
            "confidence": option.confidence,
            "evidence": ids(option.evidence),
            "reasons": [
                {
                    "stance": reason.stance,
                    "text": reason.text,
                    "support": reason.support,
                    "evidence": ids(reason.evidence),
                }
                for reason in option.reasons
            ],
            "history": [
                {
                    "post_id": event.post_id,
                    "act": event.act,
                    "role": event.role,
                    "author": event.author,
                    "evidence_type": event.evidence_type,
                    "support": event.support,
                    "status_after": event.status_after,
                    "evidence": ids(event.evidence),
                }
                for event in option.status_history
            ],
        }
        for option in record.options
    ]
    items = []
    for ev in evidence:
        item: dict[str, Any] = {
            "id": ev_ids[_evidence_key(ev)],
            "source": by_post[ev.post_id].id,
            "kind": "discussion_post",
            "post_id": ev.post_id,
            "post_version": ev.post_version,
        }
        if ev.post_sha256:
            item["digest"] = f"sha256:{ev.post_sha256}"
        item.update(
            {
                "sentence_indexes": list(ev.sentence_indexes),
                "start": ev.start,
                "end": ev.end,
                "quote": ev.quote,
                "url": ev.url,
                "source_check": ev.source_check,
                "support": ev.support,
                "evidence_type": ev.evidence_type,
            }
        )
        items.append(item)
    code = [
        {
            "repo": link.repo,
            "path": link.path,
            "commit": link.commit,
            "pr": link.pr,
            "method": link.method,
            "strength": link.strength,
        }
        for link in record.code_links
    ]
    run = record.run
    return {
        "schema": RECORD_SCHEMA,
        "id": record.id,
        "question": record.question,
        "thread_id": record.thread_id,
        "decided_by": _decided_by(record.decided_by),
        "decided_in_post": record.decided_in_post,
        "verification": record.verification,
        "model": run.model if run is not None else None,
        "run_mode": run.mode if run is not None else None,
        "prompt_version": run.prompt_version if run is not None else None,
        "support_checked": run.support_checked if run is not None else False,
        "options": options,
        "evidence": items,
        "code": code,
    }


def _front(record: DecisionRecord, thread: Thread | None, sources: list[_Source], evidence: list[Evidence]) -> dict:
    """OKF frontmatter. There is no ``stale_after``: DecRack applies no age decay to decisions."""
    at = _iso(_generated_at(record))
    front: dict[str, Any] = {
        "type": "Decision Record",
        "title": _title(record),
        "description": _description(record),
    }
    if record.thread_url:
        front["resource"] = record.thread_url
    front["tags"] = _tags(record, thread)
    front["status"] = "stable" if record.verification in VERIFIED_STATES else "draft"
    version = record.run.decrack_version if record.run is not None else __version__
    front["generated"] = {"by": f"decrack/{version}", "at": at}
    if record.verification == "machine_checked":
        front["verified"] = [{"by": QUOTE_CHECKER, "at": at}]
    platform = _platform(record, thread)
    front["sources"] = [_source_entry(source, platform) for source in sources]
    front["decrack"] = _decrack_block(record, sources, evidence)
    return front


# Body ----------------------------------------------------------------------------


def _outcome(record: DecisionRecord, by_post: dict[str, _Source]) -> str:
    parts = [_sentence(_md(record.outcome))] if record.outcome.strip() else []
    who = record.decided_by
    by = f" by {_md(who.handle)} ({who.role})" if who is not None else ""
    if record.decided_in_post:
        source = by_post.get(record.decided_in_post)
        name = _post_name(source) if source is not None else record.decided_in_post
        parts.append(f"Decided in post {name}{by}." + (f"[^{source.id}]" if source is not None else ""))
    elif who is not None:
        parts.append(f"Decided{by}.")
    else:
        parts.append("No deciding post was identified.")
    return " ".join(parts)


def _main_reason(option: Option) -> str:
    wanted = "pro" if option.status == "accepted" else "con" if option.status in REJECTED_STATUSES else None
    for reason in option.reasons:
        if reason.stance == wanted:
            return reason.text
    return option.reasons[0].text if option.reasons else ""


def _options_table(record: DecisionRecord) -> list[str]:
    if not record.options:
        return ["No options recorded."]
    lines = ["| Option | Status | Kind | Confidence | Main reason |", "|---|---|---|---|---|"]
    for option in record.options:
        reason = _cell(_main_reason(option)) or "-"
        lines.append(
            f"| {_cell(option.title)} ({_cell(option.key)}) | {option.status} | {option.status_kind}"
            f" | {option.confidence} | {reason} |"
        )
    return lines


def _status_line(option: Option, by_post: dict[str, _Source]) -> str:
    """``Status: rejected (confirmed, confidence high). Basis: author statement by alice (author) in post #5.``"""
    text = f"Status: {option.status} ({option.status_kind}, confidence {option.confidence})."
    basis = BASIS_TEXT.get(option.status_basis)
    if basis:
        text += f" Basis: {basis}"
        if option.decided_by is not None:
            text += f" by {_md(option.decided_by.handle)} ({option.decided_by.role})"
        source = by_post.get(option.status_post) if option.status_post else None
        if source is not None:
            text += f" in post {_post_name(source)}.[^{source.id}]"
        elif option.status_post:
            text += f" in post {option.status_post}."
        else:
            text += "."
    if option.status_note.strip():
        text += " " + _sentence(_md(option.status_note))
    return text


def _rejected_ideas(record: DecisionRecord, by_post: dict[str, _Source]) -> list[str]:
    rejected = [option for option in record.options if option.status in REJECTED_STATUSES]
    if not rejected:
        return ["None recorded."]
    lines: list[str] = []
    for option in rejected:
        lines += [f"## {_md(option.title)}", "", _status_line(option, by_post), ""]
        for reason in option.reasons:
            lines.append(f"- {reason.stance}: {_md(reason.text)}{_feet(reason.evidence, by_post)}")
        if not option.reasons:
            lines.append(f"- No reason was recorded.{_feet(option.evidence, by_post)}")
        lines.append("")
    return lines[:-1]


def _code(record: DecisionRecord) -> list[str]:
    if not record.code_links:
        return ["No code links recorded."]
    lines = []
    for link in record.code_links:
        where = [link.repo, f"PR #{link.pr}" if link.pr is not None else "", f"commit {link.commit}" if link.commit else ""]
        place = ", ".join(part for part in where if part)
        lines.append(f"- `{link.path}`" + (f" ({place})" if place else "") + f": {link.method}, {link.strength}")
    return lines


def _evidence_section(evidence: list[Evidence], sources: list[_Source], by_post: dict[str, _Source]) -> list[str]:
    lines = [
        "Each quote below is the exact text `text[start:end]` of the cited sentences in one version of a post."
        " The `decrack.evidence` list in the frontmatter holds the same quotes with their post IDs, post"
        " versions, digests, sentence indexes, offsets, source checks and support verdicts.",
        "",
    ]
    for ev in evidence:
        lines.append(f"- > {_md(ev.quote)} ({_cite(ev)}){_feet([ev], by_post)}")
    if not evidence:
        lines.append("No evidence recorded.")
    if sources:
        lines.append("")
        lines += [f"[^{source.id}]: {_footnote(source)}" for source in sources]
    return lines


def _body(record: DecisionRecord, sources: list[_Source], evidence: list[Evidence]) -> str:
    by_post = {source.post_id: source for source in sources}
    lines = ["# Question", "", _md(record.question) or "No question recorded.", ""]
    lines += ["# Decision outcome", "", _outcome(record, by_post), ""]
    lines += ["# Considered options", "", *_options_table(record), ""]
    lines += ["# Rejected ideas", "", *_rejected_ideas(record, by_post), ""]
    lines += ["# Code", "", *_code(record), ""]
    lines += ["# Evidence", "", *_evidence_section(evidence, sources, by_post)]
    return "\n".join(lines) + "\n"


# Public API -----------------------------------------------------------------------


def render_record(record: DecisionRecord, thread: Thread | None = None) -> str:
    """One record file: OKF frontmatter, then a MADR-style body with footnoted sources.

    With the record's ``thread``, sources gain post numbers, thread order and post
    times; without it they come from the evidence alone (post id, URL, author).
    """
    if thread is not None and thread.id != record.thread_id:
        thread = None
    sources = _collect_sources(record, thread)
    evidence = _unique_evidence(record)
    return _frontmatter(_front(record, thread, sources, evidence)) + "\n" + _body(record, sources, evidence)


def record_filename(record: DecisionRecord) -> str:
    """``dr-xxxxxxxx-<slug>.md``: the record id and a slug of the question."""
    return f"{record.id}-{slugify(record.question) or 'decision'}.md"


def _decisions_index(records: list[DecisionRecord]) -> str:
    lines = ["# Decisions", ""]
    for record in records:
        title = _title(record).replace("[", "\\[").replace("]", "\\]")
        lines.append(f"* [{title}]({record_filename(record)}) - {_description(record)}")
    if not records:
        lines.append("No decision records yet.")
    return "\n".join(lines) + "\n"


def _log(records: list[DecisionRecord]) -> str:
    """Creation and verification entries under ``## YYYY-MM-DD`` headings, newest first."""
    lines: list[str] = []
    day = ""
    for record in sorted(records, key=lambda r: (_generated_at(r), r.id), reverse=True):
        when = _generated_at(record).strftime("%Y-%m-%d")
        if when != day:
            lines += ([""] if lines else []) + [f"## {when}", ""]
            day = when
        evidence = _unique_evidence(record)
        valid = sum(1 for ev in evidence if ev.source_check == "valid")
        # "Passed" only when the record is machine-checked and every quote's source check is valid.
        if record.verification == "machine_checked" and evidence and valid == len(evidence):
            lines.append(
                f"* **Verification**: quote check passed for [{record.id}](decisions/{record_filename(record)}),"
                f" {valid} of {len(evidence)} quotes valid."
            )
        lines.append(f"* **Creation**: extracted {record.id} from {record.thread_url or record.thread_id}.")
    return "\n".join(lines or ["No entries yet."]) + "\n"


def _root_index() -> str:
    return (
        _frontmatter({"okf_version": OKF_VERSION})
        + "\n# Projects\n\n"
        + "* [Decisions](decisions/index.md) - Decision records recovered by DecRack"
        + f" (OKF v{OKF_VERSION}, spec commit {OKF_SPEC_COMMIT}).\n"
    )


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def export_bundle(
    records: list[DecisionRecord],
    out_dir: str | Path,
    threads: dict[str, Thread] | None = None,
) -> list[Path]:
    """Write the OKF bundle under ``out_dir`` and return the paths written.

    ``threads`` (by thread id) adds post numbers, thread order and post times to the
    sources. Record files from earlier exports that are not in this one are removed.
    """
    out = Path(out_dir)
    decisions_dir = out / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    threads = threads or {}
    unique = {record.id: record for record in records}
    ordered = sorted(unique.values(), key=lambda r: (_title(r).casefold(), r.id))
    written: list[Path] = []
    for record in ordered:
        text = render_record(record, threads.get(record.thread_id))
        written.append(_write(decisions_dir / record_filename(record), text))
    current = {path.name for path in written}
    for stale in sorted(decisions_dir.glob("dr-*.md")):
        if stale.name not in current:
            stale.unlink()
    written.append(_write(decisions_dir / "index.md", _decisions_index(ordered)))
    written.append(_write(out / "log.md", _log(ordered)))
    written.append(_write(out / "index.md", _root_index()))
    return written
