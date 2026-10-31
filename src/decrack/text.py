"""Text helpers: Unicode normalization, sentence spans, hashing, time parsing, slugs.

``sentence_spans`` is the basis of every citation. Each span is a pair of
character offsets ``(start, end)`` into the post's NFC-normalized text. Its
invariant: every sentence ``text[start:end]`` is stripped and non-empty, spans
come in order without overlapping, every non-whitespace character belongs to
exactly one span, and consecutive spans are separated only by whitespace. A
quote is always ``text[first.start:last.end]`` for a run of cited sentences,
so it can be re-checked exactly against the stored post version.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from decrack.models import Post, Span, Thread

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}(?:\s|$)")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+\S")

# A sentence ends at . ! or ? (plus closing quotes or brackets) when whitespace
# and then a capital letter, digit, quote, bracket, backtick or emphasis follow.
BOUNDARY_RE = re.compile(r"[.!?]+[\"'”’)\]]*(?=\s+[\"'“‘(\[`*_]*[A-Z0-9`])")
ABBREVIATIONS = {
    "e.g.", "i.e.", "etc.", "vs.", "cf.", "approx.", "mr.", "mrs.", "ms.", "dr.", "prof.",
    "fig.", "al.", "inc.", "ltd.", "vol.", "pp.", "ca.", "resp.", "esp.", "jr.", "sr.", "st.",
}
INITIAL_RE = re.compile(r"^[A-Z]\.$")

TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d")


def nfc(text: str) -> str:
    """NFC-normalize text, so "e" + combining accent and "\u00e9" hash and match the same."""
    return unicodedata.normalize("NFC", text or "")


def normalize_ws(text: str) -> str:
    """Collapse every run of whitespace to one space and strip the ends."""
    return " ".join(text.split())


def sha256_text(text: str) -> str:
    """Hex sha256 of the NFC-normalized UTF-8 text; stored per post to detect edited sources."""
    return hashlib.sha256(nfc(text).encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Rough token count (about four characters per token)."""
    return len(text) // 4 + 1


def _starts_block(line: str) -> bool:
    return bool(FENCE_RE.match(line) or HEADING_RE.match(line) or LIST_ITEM_RE.match(line))


def _blocks(text: str) -> list[tuple[str, int, int]]:
    """Split text into (kind, start, end) blocks: code, heading, item or para."""
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)

    blocks: list[tuple[str, int, int]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        start = offsets[i]
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            j = i + 1
            while j < len(lines) and not lines[j].lstrip().startswith(marker):
                j += 1
            last = min(j, len(lines) - 1)  # an unclosed fence runs to the end
            blocks.append(("code", start, offsets[last] + len(lines[last])))
            i = last + 1
            continue
        if HEADING_RE.match(line):
            blocks.append(("heading", start, start + len(line)))
            i += 1
            continue
        kind = "item" if LIST_ITEM_RE.match(line) else "para"
        j = i + 1
        while j < len(lines) and lines[j].strip() and not _starts_block(lines[j]):
            j += 1
        blocks.append((kind, start, offsets[j - 1] + len(lines[j - 1])))
        i = j
    return blocks


def _is_abbreviation(paragraph: str, dot_index: int) -> bool:
    """True when the word ending at ``dot_index`` is an abbreviation or an initial."""
    words = paragraph[: dot_index + 1].split()
    if not words:
        return False
    word = words[-1].lstrip("(\"'“‘")
    return word.lower() in ABBREVIATIONS or bool(INITIAL_RE.match(word))


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    """``(start, end)`` moved inwards past whitespace; None when nothing is left."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _paragraph_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    paragraph = text[start:end]
    spans: list[tuple[int, int]] = []
    last = 0
    for match in BOUNDARY_RE.finditer(paragraph):
        if _is_abbreviation(paragraph, match.start()):
            continue
        piece = _trim(text, start + last, start + match.end())
        if piece:
            spans.append(piece)
        last = match.end()
    tail = _trim(text, start + last, end)
    if tail:
        spans.append(tail)
    return spans


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Character offsets ``(start, end)`` of each citable unit of ``text``.

    Fenced code blocks, headings and list items (with their wrapped lines)
    stay whole; paragraphs split into sentences.
    """
    spans: list[tuple[int, int]] = []
    for kind, start, end in _blocks(text or ""):
        if kind == "para":
            spans.extend(_paragraph_spans(text, start, end))
        else:
            piece = _trim(text, start, end)
            if piece:
                spans.append(piece)
    return spans


def split_sentences(text: str) -> list[str]:
    """The sentences of ``text``: ``text[start:end]`` for every span."""
    return [text[start:end] for start, end in sentence_spans(text or "")]


def parse_time(value: object) -> datetime | None:
    """Parse ISO strings (with ``Z`` or an offset), epoch numbers, mail dates and datetimes.

    Always returns a timezone-aware UTC datetime, or None when the value is
    missing or unreadable. Naive values are taken to be UTC.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e12 else value  # milliseconds since the epoch
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        moment = _parse_time_string(value.strip())
        if moment is None:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _parse_time_string(value: str) -> datetime | None:
    if not value:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return parse_time(float(value))
    cleaned = re.sub(r"\s*(?:UTC|GMT)$", "", value)
    if cleaned.endswith(("Z", "z")):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        pass
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None


def finalize_post(post: Post) -> Post:
    """NFC-normalize a post's text, then fill its sentence spans, sentences and content hash."""
    post.text = nfc(post.text)
    offsets = sentence_spans(post.text)
    post.spans = [Span(index=index, start=start, end=end) for index, (start, end) in enumerate(offsets, start=1)]
    post.sentences = [post.text[start:end] for start, end in offsets]
    post.sha256 = sha256_text(post.text)
    return post


def quote_range(post: Post, indexes: list[int]) -> tuple[int, int, str]:
    """``(start, end, quote)`` for a contiguous run of 1-based sentence ``indexes`` of ``post``.

    The quote is exactly ``post.text[start:end]``, from the first sentence's start
    to the last sentence's end. Raises ValueError for an empty, out-of-range or
    non-contiguous run.
    """
    ordered = sorted(indexes)
    if not ordered or ordered != list(range(ordered[0], ordered[0] + len(ordered))):
        raise ValueError(f"sentence indexes {indexes} are not one contiguous run")
    if ordered[0] < 1 or ordered[-1] > len(post.spans):
        raise ValueError(f"sentence indexes {indexes} are out of range for post {post.id}")
    start, end = post.spans[ordered[0] - 1].start, post.spans[ordered[-1] - 1].end
    return start, end, post.text[start:end]


def finalize_thread(thread: Thread) -> Thread:
    """Finalize every post of the thread; returns the same thread."""
    for post in thread.posts:
        finalize_post(post)
    return thread


def slugify(text: str, max_len: int = 50) -> str:
    """Lower-case ASCII words joined by ``-``, cut at a word boundary."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if len(slug) > max_len:
        cut = slug[:max_len]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else cut
    return slug.strip("-") or "untitled"
