"""``pep:N`` resolver: a PEP's discussion threads, never the PEP text.

``https://peps.python.org/api/peps.json`` lists each PEP's ``discussions_to``
and ``post_history`` links, and it is used for nothing else: the PEP's title,
status and resolution never enter the thread. Every discuss.python.org topic
in those links is fetched with the Discourse connector, and the posts are
merged into one thread in time order. Post ids stay the topics' own, ``seq``
is renumbered 1..n, and the thread's title is the first topic's own title.

Leak guard (evaluation mode): a post that pastes the PEP itself (its section
headings, or a very long text) is blanked, so the model cannot copy the PEP's
own "Rejected Ideas" section. The count goes into ``thread.meta["leak_blanked"]``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from decrack.models import Post, Thread
from decrack.sources.discourse import fetch_topic, topic_id_from_path, topic_to_thread
from decrack.text import finalize_thread

PEPS_API = "https://peps.python.org/api/peps.json"
DISCOURSE_FORUM = "https://discuss.python.org"
PEP_TOPIC_RE = re.compile(r"/t/([^?#\s]+)")
URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

REJECTED_HEADINGS = {"rejected ideas", "rejected alternatives"}
PEP_SECTION_HEADINGS = {
    "abstract",
    "motivation",
    "rationale",
    "specification",
    "backwards compatibility",
    "security implications",
    "how to teach this",
    "reference implementation",
    "open issues",
    "copyright",
}
LEAK_MAX_CHARS = 20000


def fetch_index(client: httpx.Client) -> dict:
    """The peps.json index: a dict keyed by PEP number as a string."""
    response = client.get(PEPS_API)
    response.raise_for_status()
    return response.json()


def topic_ids(entry: dict) -> list[int]:
    """discuss.python.org topic ids in a PEP's ``discussions_to`` and ``post_history``, in order."""
    urls = [entry.get("discussions_to") or ""]
    urls += URL_RE.findall(entry.get("post_history") or "")
    found: list[int] = []
    for url in urls:
        if "discuss.python.org" not in url:
            continue
        match = PEP_TOPIC_RE.search(url)
        # /t/slug/123/45 and /t/123/45 both name topic 123; 45 is a post number.
        topic_id = topic_id_from_path(match.group(1)) if match else None
        if topic_id is not None and topic_id not in found:
            found.append(topic_id)
    return found


def _heading_names(text: str) -> set[str]:
    """Lines that are just a heading name (with or without leading ``#``), lower-cased."""
    names = set()
    for line in text.splitlines():
        name = line.strip().lstrip("#").strip().rstrip(":").strip().lower()
        if name and len(name) <= 40:
            names.add(name)
    return names


def looks_like_pep_text(text: str) -> bool:
    """True for a post that pastes the PEP: a rejected-ideas heading, 2+ PEP sections, or > 20k chars."""
    if len(text) > LEAK_MAX_CHARS:
        return True
    headings = _heading_names(text)
    if headings & REJECTED_HEADINGS:
        return True
    return len(headings & PEP_SECTION_HEADINGS) >= 2


def _author_names(entry: dict) -> list[str]:
    """Display names from peps.json ``authors``, without e-mail addresses."""
    names = entry.get("author_names")
    if isinstance(names, list) and names:
        return [str(name).strip() for name in names if str(name).strip()]
    authors = re.sub(r"<[^>]*>", "", entry.get("authors") or "")
    return [name.strip() for name in authors.split(",") if name.strip()]


def merge_topics(topics: list[Thread]) -> list[Post]:
    """Merge the posts of several topics in time order: ids kept, ``seq`` renumbered 1..n.

    Reply and quote edges are rebuilt from each post's (topic_id, post_number)
    references, so post 2 of one topic never stands in for post 2 of another.
    """
    tagged = []
    for topic_index, topic in enumerate(topics):
        for post in topic.posts:
            tagged.append((post.created_at or EPOCH, topic_index, post.seq, post))
    tagged.sort(key=lambda item: item[:3])
    id_of: dict[tuple[int, int], str] = {}
    for _, _, _, post in tagged:
        id_of[(post.meta.get("topic_id"), post.meta.get("post_number"))] = post.id

    merged: list[Post] = []
    for seq, (_, _, _, post) in enumerate(tagged, start=1):
        topic_id = post.meta.get("topic_id")
        reply = post.meta.get("reply_to_post_number")
        quotes: list[str] = []
        for ref_topic, ref_number in post.meta.get("quote_refs") or []:
            target = id_of.get((ref_topic, ref_number))
            if target is not None and target != post.id and target not in quotes:
                quotes.append(target)
        merged.append(
            post.model_copy(
                update={
                    "seq": seq,
                    "reply_to": id_of.get((topic_id, reply)) if reply is not None else None,
                    "quotes": quotes,
                }
            )
        )
    return merged


def load_pep(number: int, client: httpx.Client, leak_guard: bool = False) -> Thread:
    """All discuss.python.org topics of PEP ``number`` as one thread (id ``pep:N``).

    The url and title are the first topic's own; peps.json only adds the topic
    ids and the authors' names (for roles).
    """
    index = fetch_index(client)
    entry = index.get(str(number)) or index.get(str(int(number)))
    if not entry:
        raise ValueError(f"PEP {number} is not in {PEPS_API}")
    ids = topic_ids(entry)
    if not ids:
        raise ValueError(f"PEP {number} links no discuss.python.org topic (discussions_to: {entry.get('discussions_to')})")

    topics = [topic_to_thread(fetch_topic(client, DISCOURSE_FORUM, topic_id), DISCOURSE_FORUM) for topic_id in ids]
    posts = merge_topics(topics)

    blanked = 0
    if leak_guard:
        for post in posts:
            if post.text and looks_like_pep_text(post.text):
                post.text = ""
                post.meta["leak_blanked"] = True
                blanked += 1

    creators: list[str] = []
    for topic in topics:
        for name in topic.meta.get("created_by") or []:
            if name not in creators:
                creators.append(name)
    thread = Thread(
        id=f"pep:{int(number)}",
        kind="discourse",
        url=topics[0].url,
        title=topics[0].title,
        posts=posts,
        meta={
            "pep": int(number),
            "pep_authors": _author_names(entry),
            "topic_ids": ids,
            "created_by": creators,
            "forum": DISCOURSE_FORUM,
            "posts_count": len(posts),
            "leak_blanked": blanked,
        },
    )
    # Re-finalize so blanked posts get no sentences or spans, and the hash of "".
    return finalize_thread(thread)
