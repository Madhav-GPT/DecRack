"""Discourse connector (discuss.python.org or any Discourse forum).

One request per topic: ``GET {forum}/t/{id}.json?print=true`` returns the whole
topic, up to 1,000 posts, with metadata and ``cooked`` HTML. The HTML is turned
into text with the stdlib ``html.parser``. Quote blocks (``<aside class="quote">``)
are dropped from a post's own text but kept as quote edges; every other
``<aside>`` (link previews) is dropped too, because it can paste outside text.

Identity is Discourse's own and does not depend on order: a post is
``dpo:{topic_id}:{post id}``, its ``source_post_number`` is Discourse's
``post_number`` and its ``version`` is Discourse's edit ``version``. ``seq``
is only the post's place in the thread, and the reply and quote edges hold
post ids, never positions.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from decrack.models import Post, Thread
from decrack.text import finalize_thread, parse_time

DEFAULT_FORUM = "https://discuss.python.org"
TOPIC_URL_RE = re.compile(r"^(https?://[^/\s]+)/t/([^?#\s]+)")
MAX_RETRIES = 3
MAX_RETRY_WAIT = 30.0
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

BLOCK_TAGS = {
    "p", "div", "blockquote", "table", "thead", "tbody", "tr", "ul", "ol", "dl", "dt", "dd",
    "details", "summary", "section", "article", "figure", "figcaption", "hr",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIPPED_TAGS = {"aside", "script", "style", "svg", "noscript"}
VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}


class _CookedParser(HTMLParser):
    """Collects a post's own text from Discourse ``cooked`` HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.quote_refs: list[tuple[int | None, int]] = []
        self.skip_tag: str | None = None
        self.skip_depth = 0
        self.in_pre = 0
        self.in_inline_code = False
        self.lists: list[list] = []  # one [kind, counter] per open <ul>/<ol>
        self.in_item = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        classes = attributes.get("class", "").split()
        if tag in SKIPPED_TAGS or (tag == "div" and "lightbox-wrapper" in classes):
            if tag == "aside" and "quote" in classes:
                self._record_quote(attributes)
            if tag not in VOID_TAGS:
                self.skip_tag, self.skip_depth = tag, 1
            return
        if tag == "pre":
            self.in_pre += 1
            self.parts.append("\n\n```\n")
        elif tag == "code":
            if not self.in_pre:
                self.in_inline_code = True
                self.parts.append("`")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "img":
            if "emoji" in classes and attributes.get("alt"):
                self.parts.append(attributes["alt"])
        elif tag in HEADING_TAGS:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            self.parts.append("\n")
        elif tag == "li":
            self.in_item += 1
            depth = max(len(self.lists), 1)
            marker = "-"
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                marker = f"{self.lists[-1][1]}."
            self.parts.append("\n" + "  " * (depth - 1) + marker + " ")
        elif tag in ("td", "th"):
            self.parts.append(" ")
        elif tag == "p" and self.in_item:
            self.parts.append(" ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return
        if tag == "pre":
            self.in_pre = max(self.in_pre - 1, 0)
            self.parts.append("\n```\n\n")
        elif tag == "code":
            if self.in_inline_code:
                self.in_inline_code = False
                self.parts.append("`")
        elif tag in HEADING_TAGS:
            self.parts.append("\n\n")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self.parts.append("\n\n")
        elif tag == "li":
            self.in_item = max(self.in_item - 1, 0)
            self.parts.append("\n")
        elif tag == "p" and self.in_item:
            self.parts.append("\n")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self.skip_tag is not None:
            return
        if self.in_pre:
            self.parts.append(data)
        else:
            # HTML whitespace is not significant; structure comes from the tags.
            self.parts.append(re.sub(r"\s+", " ", data))

    def _record_quote(self, attributes: dict[str, str]) -> None:
        post = attributes.get("data-post", "")
        if not post.isdigit():
            return
        topic = attributes.get("data-topic", "")
        self.quote_refs.append((int(topic) if topic.isdigit() else None, int(post)))

    def text(self) -> str:
        lines = [line.rstrip() for line in "".join(self.parts).split("\n")]
        joined = "\n".join(line if line.strip() else "" for line in lines)
        return re.sub(r"\n{3,}", "\n\n", joined).strip()


def _convert(html: str) -> tuple[str, list[tuple[int | None, int]]]:
    parser = _CookedParser()
    parser.feed(html or "")
    parser.close()
    return parser.text(), parser.quote_refs


def cooked_to_text(html: str) -> tuple[str, list[int]]:
    """A post's own text from ``cooked`` HTML, plus the post numbers it quotes."""
    text, refs = _convert(html)
    return text, [post_number for _, post_number in refs]


def topic_id_from_path(path: str) -> int | None:
    """The topic id in the part of a URL after ``/t/``: its first all-digit segment.

    ``slug/123/45`` and ``123/45`` both give 123 (45 is a post number).
    """
    for segment in path.strip("/").split("/"):
        if segment.isdigit():
            return int(segment)
    return None


def parse_topic_ref(url_or_id: str | int, forum: str = DEFAULT_FORUM) -> tuple[str, int]:
    """Return (forum, topic_id) for a topic URL or a bare topic id."""
    if isinstance(url_or_id, int):
        return forum.rstrip("/"), url_or_id
    value = str(url_or_id).strip()
    if value.isdigit():
        return forum.rstrip("/"), int(value)
    match = TOPIC_URL_RE.match(value)
    topic_id = topic_id_from_path(match.group(2)) if match else None
    if topic_id is None:
        raise ValueError(f"Not a Discourse topic URL: {value!r} (expected https://host/t/slug/123)")
    return match.group(1), topic_id


def fetch_topic(client: httpx.Client, forum: str, topic_id: int) -> dict:
    """Fetch one whole topic as JSON, waiting out rate limits (HTTP 429)."""
    url = f"{forum.rstrip('/')}/t/{topic_id}.json"
    for attempt in range(MAX_RETRIES + 1):
        response = client.get(url, params={"print": "true"})
        if response.status_code == 429 and attempt < MAX_RETRIES:
            time.sleep(_retry_after(response))
            continue
        if response.status_code == 404:
            raise ValueError(f"Discourse topic {topic_id} was not found at {forum}")
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"Discourse kept rate-limiting requests for topic {topic_id}")


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(max(float(response.headers.get("Retry-After", "5")), 0.0), MAX_RETRY_WAIT)
    except ValueError:
        return 5.0


def _int(value: object) -> int | None:
    """An int from JSON (an int or a string of digits); None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _post_id(topic_id: int, raw: dict, post_number: int) -> str:
    """``dpo:{topic_id}:{post id}``; a saved topic without post ids falls back to ``p{post_number}``."""
    discourse_id = _int(raw.get("id"))
    native = str(discourse_id) if discourse_id is not None else f"p{post_number}"
    return f"dpo:{topic_id}:{native}"


def topic_to_thread(data: dict, forum: str = DEFAULT_FORUM) -> Thread:
    """Turn a topic's JSON into a Thread ordered by post time, with stable post ids."""
    forum = forum.rstrip("/")
    topic_id = _int(data.get("id")) or 0
    slug = data.get("slug") or "topic"
    raw_posts = (data.get("post_stream") or {}).get("posts") or []

    items = []
    for index, raw in enumerate(raw_posts, start=1):
        post_number = _int(raw.get("post_number"))
        if post_number is None:
            post_number = index  # a hand-made topic without post numbers: use their order
        text, refs = _convert(raw.get("cooked") or "")
        items.append((parse_time(raw.get("created_at")), index, post_number, raw, text, refs))
    items.sort(key=lambda item: (item[0] or EPOCH, item[1]))
    # Edges name posts by post_number; they resolve to ids inside this topic only.
    id_of = {post_number: _post_id(topic_id, raw, post_number) for _, _, post_number, raw, _, _ in items}

    posts: list[Post] = []
    for seq, (created, _, post_number, raw, text, refs) in enumerate(items, start=1):
        post_id = _post_id(topic_id, raw, post_number)
        reply_number = _int(raw.get("reply_to_post_number"))
        quotes: list[str] = []
        for ref_topic, ref_number in refs:
            target = id_of.get(ref_number) if ref_topic in (None, topic_id) else None
            if target is not None and target != post_id and target not in quotes:
                quotes.append(target)
        meta = {
            "topic_id": topic_id,
            "post_number": post_number,
            "username": raw.get("username") or "",
            "name": raw.get("name") or "",
            "user_title": raw.get("user_title") or "",
            "flair_name": raw.get("flair_name") or "",
            "primary_group_name": raw.get("primary_group_name") or "",
            "moderator": bool(raw.get("moderator")),
            "admin": bool(raw.get("admin")),
            "staff": bool(raw.get("staff")),
            "reply_to_post_number": reply_number,
            "quote_refs": [[ref_topic if ref_topic is not None else topic_id, number] for ref_topic, number in refs],
        }
        posts.append(
            Post(
                id=post_id,
                source_id=f"dpo:t{topic_id}",
                source_post_number=post_number,
                seq=seq,
                version=_int(raw.get("version")) or 1,
                author=raw.get("username") or "unknown",
                created_at=created,
                reply_to=id_of.get(reply_number) if reply_number is not None else None,
                quotes=quotes,
                url=f"{forum}/t/{slug}/{topic_id}/{post_number}",
                text=text,
                meta=meta,
            )
        )

    creator = ((data.get("details") or {}).get("created_by") or {}).get("username")
    if not creator and posts:
        creator = posts[0].author
    thread = Thread(
        id=f"dpo:t{topic_id}",
        kind="discourse",
        url=f"{forum}/t/{slug}/{topic_id}",
        title=data.get("title") or data.get("fancy_title") or f"Topic {topic_id}",
        posts=posts,
        meta={
            "created_by": [creator] if creator else [],
            "topic_ids": [topic_id],
            "forum": forum,
            "posts_count": data.get("posts_count", len(posts)),
        },
    )
    return finalize_thread(thread)


def load_topic(url_or_id: str | int, client: httpx.Client, forum: str = DEFAULT_FORUM) -> Thread:
    """Fetch a topic by URL or id and return it as a Thread."""
    forum, topic_id = parse_topic_ref(url_or_id, forum)
    return topic_to_thread(fetch_topic(client, forum, topic_id), forum)
