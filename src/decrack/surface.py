"""PR-time surfacing: related history and possible conflicts for a change.

``check_change`` collects the paths and PR numbers a change touches (from a
GitHub PR, a list of paths, or a local ``BASE..HEAD`` diff whose changed lines
are blamed), finds the decision records linked to them, and renders a markdown
report. The report is history to weigh, never a verdict on the change: a
rejected option it lists is a possible conflict for a person to check. It only
returns data and text; it never posts anywhere.

Each match carries the strength of its best link: ``direct`` (the thread names
the file or is the PR under review), ``historical`` (git facts: the files a PR
changed, or blame) or ``suggested`` (a text match only).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from decrack import linking
from decrack.models import DecisionRecord, Evidence, Option
from decrack.search import NOTICE, pack
from decrack.sources import github as github_source

if TYPE_CHECKING:
    import httpx

    from decrack.store import Store

REPORT_TITLE = "## DecRack: related history / possible conflict"
HISTORY_NOTE = (
    "These are recorded discussions related to this change. A rejected option listed here is a possible "
    "conflict to check, not a ruling on the change."
)
NO_MATCHES = "No related history: no recorded decisions touch these files or PRs."
POSSIBLE_CONFLICT = (
    "Possible conflict: if this change brings back an option rejected above, read the linked discussion "
    "and its reasons before merging."
)
REJECTED_LIKE = ("rejected", "withdrawn", "deferred", "superseded")
STRENGTHS = ("direct", "historical", "suggested")  # strongest first
MAX_PATHS_SHOWN = 20
QUOTE_CHARS = 300
TEXT_MATCH_LIMIT = 5
THREAD_PR_RE = re.compile(r"#(\d+)$")
# The store ORs query words together, so words this common would match every record.
QUERY_STOPWORDS = frozenset(
    "the and for with this that from into are was were has have not but you your our its can will "
    "would should could also use using add adds added fix fixes make makes when what which why how".split()
)


def check_change(
    store: Store,
    *,
    pr_url: str | None = None,
    paths: list[str] | None = None,
    description: str | None = None,
    diff: str | None = None,
    repo_dir: str | Path | None = None,
    client: httpx.Client | None = None,
    budget_tokens: int = 10000,
) -> dict[str, Any]:
    """Decision records related to a change: a dict with ``paths``, ``prs``, ``matches`` and ``markdown``.

    The inputs add up. A PR URL brings its files, number, title and body. A
    ``diff`` ("BASE..HEAD" in the clone at ``repo_dir``) brings the changed
    files, their earlier names, and the PRs that last touched the changed lines.
    """
    base_head = _split_range(diff, repo_dir) if diff else None
    checked: list[str] = []
    prs: set[int] = set()
    reviewed_pr: int | None = None  # the PR under review, when pr_url is given
    repo: str | None = None
    texts = [description] if description else []
    earlier_names: dict[str, str] = {}  # an earlier name -> the path it has in the change

    def add_path(path: str) -> None:
        path = path.strip()
        if path and path not in checked:
            checked.append(path)

    if isinstance(paths, str):
        paths = [paths]
    for path in paths or []:
        add_path(path)

    if pr_url:
        try:
            summary = github_source.pr_summary(pr_url, client)
        except RuntimeError as exc:  # e.g. the GitHub rate limit
            raise ValueError(f"cannot read {pr_url}: {exc}") from exc
        repo = f"{summary['owner']}/{summary['repo']}"
        reviewed_pr = int(summary["number"])
        prs.add(reviewed_pr)
        for path in summary.get("files") or []:
            add_path(str(path))
        texts += [text for text in (summary.get("title"), summary.get("body")) if text]

    if base_head is not None:
        base, head = base_head
        try:
            changed, blamed = linking.prs_for_change(repo_dir, base, head)
            history = {path: linking.follow_renames(repo_dir, path)[1:] for path in changed}
        except RuntimeError as exc:
            raise ValueError(f"cannot read the change {diff} in {repo_dir}: {exc}") from exc
        repo = repo or linking.origin_repo(repo_dir)
        prs.update(blamed)
        for path in changed:
            add_path(path)
        for path, names in history.items():
            for name in names:
                earlier_names.setdefault(name, path)
                add_path(name)

    found: dict[str, dict[str, Any]] = {}

    def note(record: DecisionRecord, why: str, strength: str) -> None:
        """Remember why a record matched; its strength is that of its strongest link."""
        entry = found.setdefault(record.id, {"record": record, "why": [], "strength": strength})
        if why not in entry["why"]:
            entry["why"].append(why)
        if _rank(strength) < _rank(entry["strength"]):
            entry["strength"] = strength

    if checked:
        for record, link in store.records_for_paths(checked):
            why = f"file {link.path} ({link.method}, {link.strength})"
            if link.path in earlier_names:
                why += f", earlier name of {earlier_names[link.path]}"
            note(record, why, link.strength)
    if prs:
        for record, link in store.records_for_prs(repo, sorted(prs)):
            if link is not None:
                note(record, f"PR #{link.pr}", link.strength)
                continue
            # No link: the record was compiled from the PR's own thread. That is the change
            # itself when it is the PR under review, else a PR that blame led to.
            number = _thread_pr(record.thread_id)
            strength = "direct" if number is not None and number == reviewed_pr else "historical"
            note(record, f"PR #{number}" if number is not None else "PR", strength)
    query = _query_words(" ".join(texts))
    if query:
        for record in store.search_records(query, limit=TEXT_MATCH_LIMIT):
            note(record, "text match", "suggested")

    entries = sorted(found.values(), key=lambda entry: (_rank(entry["strength"]), -len(entry["why"])))
    result: dict[str, Any] = {
        "paths": checked,
        "prs": sorted(prs),
        "matches": [_match_view(entry["record"], entry["why"], entry["strength"]) for entry in entries],
    }
    result["markdown"] = render_report(result, budget_tokens)
    return result


def render_report(result: dict[str, Any], budget_tokens: int = 10000) -> str:
    """Markdown for a ``check_change`` result, cut to about ``budget_tokens`` tokens."""
    matches = result.get("matches") or []
    sections = [_report_header(result)]
    if not matches:
        sections.append(NO_MATCHES)
    sections.extend(_render_match(match) for match in matches)
    return pack(sections, budget_tokens)


def _rank(strength: str) -> int:
    """0 for direct, 1 for historical, 2 for suggested; anything else ranks last."""
    return STRENGTHS.index(strength) if strength in STRENGTHS else len(STRENGTHS)


def _split_range(diff: str, repo_dir: str | Path | None) -> tuple[str, str]:
    """``"BASE..HEAD"`` -> ``("BASE", "HEAD")``; ValueError without a clone or for another shape."""
    if repo_dir is None:
        raise ValueError("a diff needs repo_dir, the local clone that holds both commits")
    base, sep, head = diff.strip().partition("..")
    if not sep or not base or not head or head.startswith("."):
        raise ValueError(f"expected a commit range BASE..HEAD, got {diff!r}")
    return base, head


def _thread_pr(thread_id: str) -> int | None:
    """The number in a GitHub thread id such as ``gh:python/cpython#123``."""
    match = THREAD_PR_RE.search(thread_id)
    return int(match.group(1)) if match else None


def _query_words(text: str) -> str:
    """The words of a description worth searching for, in order, each once."""
    words: list[str] = []
    for word in re.findall(r"\w+", text.lower()):
        if len(word) >= 3 and word not in QUERY_STOPWORDS and word not in words:
            words.append(word)
    return " ".join(words)


def _match_view(record: DecisionRecord, why: list[str], strength: str) -> dict[str, Any]:
    """One match as plain data: the record, why it matched, and its rejected, then accepted, options."""
    rejected = [option for option in record.options if option.status in REJECTED_LIKE]
    accepted = [option for option in record.options if option.status == "accepted"]
    return {
        "record_id": record.id,
        "question": record.question,
        "outcome": record.outcome,
        "thread_url": record.thread_url,
        "why": why,
        "strength": strength,
        "options": [_option_view(option) for option in rejected + accepted],
    }


def _option_view(option: Option) -> dict[str, Any]:
    """An option's reasons and checked quotes, the most telling first.

    Quotes must be source-valid, and neither quotes nor reasons are shown when
    the support check found them unsupported.
    """
    wanted = "con" if option.status in REJECTED_LIKE else "pro"
    reasons = [reason for reason in option.reasons if reason.support != "unsupported"]
    reasons.sort(key=lambda reason: reason.stance != wanted)
    evidence: list[Evidence] = []
    seen: set[tuple[str, int, int]] = set()
    for ev in [*option.evidence, *(ev for reason in option.reasons for ev in reason.evidence)]:
        key = (ev.post_id, ev.start, ev.end)
        if ev.source_check == "valid" and ev.support != "unsupported" and key not in seen:
            seen.add(key)
            evidence.append(ev)
    # The statement from the post that set the status explains the outcome best.
    evidence.sort(key=lambda ev: ev.post_id != option.status_post)
    return {
        "key": option.key,
        "title": option.title,
        "status": option.status,
        "status_kind": option.status_kind,
        "status_note": option.status_note,
        "confidence": option.confidence,
        "reasons": [reason.text for reason in reasons],
        "evidence": [{"quote": ev.quote, "url": ev.url, "author": ev.author, "post_id": ev.post_id} for ev in evidence],
    }


def _report_header(result: dict[str, Any]) -> str:
    paths = result.get("paths") or []
    prs = result.get("prs") or []
    shown = ", ".join(f"`{path}`" for path in paths[:MAX_PATHS_SHOWN]) or "none"
    if len(paths) > MAX_PATHS_SHOWN:
        shown += f" and {len(paths) - MAX_PATHS_SHOWN} more"
    pr_list = ", ".join(f"#{number}" for number in prs) or "none"
    lines = [
        REPORT_TITLE,
        "",
        f"_{NOTICE}_",
        "",
        HISTORY_NOTE,
        "",
        f"- Paths checked: {shown}",
        f"- PRs checked: {pr_list}",
        f"- Related decision records: {len(result.get('matches') or [])}",
    ]
    return "\n".join(lines)


def _render_match(match: dict[str, Any]) -> str:
    source = f"[discussion]({match['thread_url']})" if match["thread_url"] else "no link recorded"
    lines = [
        f"### {_one_line(match['question']) or match['record_id']}",
        "",
        f"- Record: `{match['record_id']}`, {source}",
        f"- Outcome: {_one_line(match.get('outcome') or '') or 'not recorded'}",
        f"- Why it matched: {'; '.join(match['why'])}",
        f"- Link strength: {match['strength']}",
    ]
    rejected = [option for option in match["options"] if option["status"] in REJECTED_LIKE]
    accepted = [option for option in match["options"] if option["status"] == "accepted"]
    if rejected or accepted:
        lines.append("")
    for option in rejected:
        lines.append(_option_line(option))
        if option["evidence"]:
            ev = option["evidence"][0]
            who = ev["author"] or "post"
            cite = f"[{who}]({ev['url']})" if ev["url"] else who
            lines.append(f"  > {_clip(_one_line(ev['quote']), QUOTE_CHARS)} ({cite})")
    for option in accepted:
        lines.append(_option_line(option))
    if rejected:
        lines += ["", POSSIBLE_CONFLICT]
    return "\n".join(lines)


def _option_line(option: dict[str, Any]) -> str:
    """``- **rejected** (confirmed): title — first reason``, plus the status note when there is one."""
    line = f"- **{option['status']}** ({option['status_kind']}): {_one_line(option['title'])}"
    if option["reasons"]:
        line += f" — {_one_line(option['reasons'][0])}"
    if option["status_note"]:
        line += f" _({_one_line(option['status_note'])})_"
    return line


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
