"""Gate: keep only candidates whose citations resolve, and build every quote in code.

The model cites prompt aliases such as ``p12.s3``; it never copies text. Each
alias is looked up in the alias table of what that call showed (the window's
parts plus the header sentences), so it resolves at once to a stable (post,
sentence index) and nothing downstream keeps an alias. An alias outside the
table is invalid, even when the thread has such a post. Candidates with no
valid alias are dropped and counted. Evidence is cut from the post's own text
at sentence boundaries, so ``quote == post.text[start:end]``. The evidence type
is derived here in code (``derive_evidence_type``), never asked of the model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from decrack.models import Candidate, Evidence, Post, Thread, sentence_alias
from decrack.text import quote_range

CITE_NOISE_RE = re.compile(r"[\s\[\](){}<>\"'`]")
CITE_SPLIT_RE = re.compile(r"[,;]")
# Words that mark an explicit decision ("added to rejected ideas", "we won't", "the SC accepts").
DECISION_CUES = re.compile(
    r"\b(rejected|added to (the )?rejected ideas|we (will not|won['’]t|are not going to)|decided|decision"
    r"|accept(ed|s)?|withdr(aw|awn|ew)|pronounce(d|ment)?|not pursue|deferred|postponed)\b",
    re.IGNORECASE,
)
DECISION_ACTS = ("accept", "reject", "defer", "withdraw")

Aliases = dict[str, tuple[Post, int]]


@dataclass
class GatedCandidate:
    """A candidate whose cites resolved, with its evidence.

    ``post``, ``role`` and ``author`` come from the latest cited post (by seq):
    an act is attributed to the writer of the latest post it cites. The
    candidate's ``cites`` are emptied; its evidence holds the stable references.
    """

    candidate: Candidate
    evidence: list[Evidence]
    post: Post
    role: str
    author: str
    evidence_type: str


@dataclass
class GateResult:
    kept: list[GatedCandidate]
    total: int
    dropped: int


def normalize_cite(cite: str) -> str:
    """``" [P12.S3] "`` -> ``"p12.s3"``: drop whitespace and brackets, lowercase."""
    return CITE_NOISE_RE.sub("", str(cite)).lower()


def split_cites(cites: Iterable[str]) -> list[str]:
    """Normalised aliases in their given order without repeats; one string may hold several ("p1.s1, p1.s2")."""
    aliases: list[str] = []
    for raw in cites:
        for part in CITE_SPLIT_RE.split(str(raw)):
            cite = normalize_cite(part)
            if cite and cite not in aliases:
                aliases.append(cite)
    return aliases


def build_aliases(posts_and_ranges: Iterable[tuple[Post, int, int]]) -> Aliases:
    """Alias table for what one prompt shows: ``sentence_alias(post.seq, i) -> (post, i)``.

    Each entry of ``posts_and_ranges`` is ``(post, first, last)``, such as a
    ``windows.WindowPart`` or ``prompts.opening_part``; indexes outside the
    post's sentences are skipped.
    """
    aliases: Aliases = {}
    for post, first, last in posts_and_ranges:
        for index in range(max(1, first), min(last, len(post.spans)) + 1):
            aliases[sentence_alias(post.seq, index)] = (post, index)
    return aliases


def resolve_aliases(aliases: Aliases, cites: Iterable[str]) -> list[tuple[Post, int]]:
    """``(post, sentence index)`` for every cite found in ``aliases``, in cite order; the rest are ignored."""
    return [aliases[cite] for cite in split_cites(cites) if cite in aliases]


def derive_evidence_type(act: str, role: str, quotes: Iterable[str]) -> str:
    """The kind of statement a candidate's quotes make, from its act, the poster's role and decision cues.

    accept/reject/defer/withdraw: "decision_statement" when a quote has a
    decision cue; otherwise "author_position" for the author, else "support"
    (accept) or "objection" (reject, defer, withdraw). object -> "objection",
    support -> "support", propose -> "proposal".
    """
    if act in DECISION_ACTS:
        if any(DECISION_CUES.search(quote or "") for quote in quotes):
            return "decision_statement"
        if role == "author":
            return "author_position"
        return "support" if act == "accept" else "objection"
    return {"object": "objection", "support": "support", "propose": "proposal"}.get(act, "other")


def make_evidence(post: Post, indexes: list[int], evidence_type: str = "other") -> Evidence:
    """Evidence for one contiguous run of sentences of ``post`` (ValueError otherwise).

    The quote is ``post.text[start:end]`` from the first sentence's start to the
    last one's end, so it can be re-checked exactly against this post version.
    """
    start, end, quote = quote_range(post, indexes)
    return Evidence(
        post_id=post.id,
        post_version=post.version,
        post_sha256=post.sha256,
        sentence_indexes=sorted(indexes),
        start=start,
        end=end,
        quote=quote,
        url=post.url,
        author=post.author,
        source_check="valid",
        support="unchecked",
        evidence_type=evidence_type,
    )


def evidence_for(pairs: Iterable[tuple[Post, int]], evidence_type: str = "other") -> list[Evidence]:
    """One Evidence per contiguous run of cited sentences of one post, posts in seq order."""
    posts: dict[str, Post] = {}
    chosen: dict[str, set[int]] = {}
    for post, index in pairs:
        posts.setdefault(post.id, post)
        chosen.setdefault(post.id, set()).add(index)
    evidence: list[Evidence] = []
    for post_id in sorted(chosen, key=lambda key: posts[key].seq):
        runs: list[list[int]] = []
        for index in sorted(chosen[post_id]):
            if runs and index == runs[-1][-1] + 1:
                runs[-1].append(index)
            else:
                runs.append([index])
        evidence.extend(make_evidence(posts[post_id], run, evidence_type) for run in runs)
    return evidence


def gate_candidates(thread: Thread, candidates: list[Candidate], aliases: Aliases) -> GateResult:
    """Keep candidates with at least one alias that resolves to a post of ``thread``; drop and count the rest.

    ``aliases`` is the table of the call that produced ``candidates`` (see
    ``build_aliases``). The evidence type comes from ``derive_evidence_type``
    (act, the latest cited post's role, the candidate's quotes) and is set on
    every evidence item of the kept candidate.
    """
    in_thread = {post.id for post in thread.posts}
    kept: list[GatedCandidate] = []
    for candidate in candidates:
        pairs = [(post, index) for post, index in resolve_aliases(aliases, candidate.cites) if post.id in in_thread]
        if not pairs:
            continue
        latest = max((post for post, _ in pairs), key=lambda post: post.seq)
        evidence = evidence_for(pairs)
        evidence_type = derive_evidence_type(candidate.act, latest.role, [item.quote for item in evidence])
        for item in evidence:
            item.evidence_type = evidence_type
        kept.append(
            GatedCandidate(
                candidate=candidate.model_copy(update={"cites": []}),
                evidence=evidence,
                post=latest,
                role=latest.role,
                author=latest.author,
                evidence_type=evidence_type,
            )
        )
    return GateResult(kept=kept, total=len(candidates), dropped=len(candidates) - len(kept))
