"""SQLite store for threads, posts, post versions, model calls and decision records.

One database file in WAL mode, the stdlib ``sqlite3`` module and plain SQL.
FTS5 indexes back the text searches when this SQLite build has FTS5; a LIKE
fallback answers the same queries without it. Open one ``Store`` per thread:
every MCP tool call opens its own.

Posts are keyed by their stable, source-native ids. ``posts`` holds the current
posts of each thread. ``post_versions`` keeps one row per (post id, version,
sha256) ever saved and never drops a text, so a citation can always be resolved
to the text that supported it, even after the post was edited. The sha256 is
part of the key because the same version can be stored twice: in full, and
blanked by the evaluation leak guard (empty text, the hash of "").
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from decrack.config import DEFAULT_DB
from decrack.models import CodeLink, DecisionRecord, Post, Thread

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    meta_json TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT NOT NULL
);
-- Keyed by (thread_id, id): a merged PEP thread and a single topic can hold the same post.
-- reply_to and quotes_json hold post ids; seq is the post's place in this thread, for display only.
CREATE TABLE IF NOT EXISTS posts (
    id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    source_post_number INTEGER,
    seq INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    author TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT,
    reply_to TEXT,
    quotes_json TEXT NOT NULL DEFAULT '[]',
    url TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    sentences_json TEXT NOT NULL DEFAULT '[]',
    spans_json TEXT NOT NULL DEFAULT '[]',
    sha256 TEXT NOT NULL DEFAULT '',
    meta_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, id)
);
CREATE INDEX IF NOT EXISTS posts_by_seq ON posts (thread_id, seq);
-- Every text a post id has had, per version; no text is ever dropped. The newest rowid is the latest fetch.
CREATE TABLE IF NOT EXISTS post_versions (
    post_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    spans_json TEXT NOT NULL DEFAULT '[]',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (post_id, version, sha256)
);
CREATE TABLE IF NOT EXISTS llm_calls (
    key TEXT PRIMARY KEY,
    step TEXT NOT NULL,
    model TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ms INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL UNIQUE,
    question TEXT NOT NULL,
    outcome TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS code_links (
    decision_id TEXT NOT NULL,
    repo TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL,
    commit_sha TEXT,
    pr INTEGER,
    method TEXT NOT NULL,
    strength TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS code_links_by_decision ON code_links (decision_id);
CREATE INDEX IF NOT EXISTS code_links_by_pr ON code_links (pr);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts
    USING fts5(decision_id UNINDEXED, body, tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts
    USING fts5(post_id UNINDEXED, thread_id UNINDEXED, text, tokenize='porter unicode61');
"""

MAX_QUERY_TOKENS = 12
SNIPPET_CHARS = 80  # LIKE fallback: characters kept on each side of the first hit
SNIPPET_TOKENS = 24  # FTS5 snippet() length
IDS_PER_QUERY = 500  # ids bound per "IN (...)" query, well under SQLite's variable limit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def query_tokens(query: str) -> list[str]:
    """Lower-cased ``\\w+`` words of a search query, deduplicated and capped."""
    tokens: list[str] = []
    for token in re.findall(r"\w+", query.lower()):
        if token not in tokens and any(ch.isalnum() for ch in token):
            tokens.append(token)
    return tokens[:MAX_QUERY_TOKENS]


def _fts_query(tokens: list[str]) -> str:
    # Quoting each token makes FTS5 read operators and punctuation as plain words.
    return " OR ".join(f'"{token}"' for token in tokens)


def _like_pattern(token: str) -> str:
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _like_hits(column_sql: str, count: int) -> str:
    """SQL that counts how many of ``count`` LIKE patterns match ``column_sql``."""
    return " + ".join(f"({column_sql} LIKE ? ESCAPE '\\')" for _ in range(count))


def _record_body(record: DecisionRecord) -> str:
    """The text the decision index covers: question, outcome, option titles and summaries, reasons, quotes."""
    parts = [record.question, record.outcome]
    quotes: list[str] = []
    for option in record.options:
        parts += [option.title, option.summary]
        evidence = list(option.evidence)
        for reason in option.reasons:
            parts.append(reason.text)
            evidence.extend(reason.evidence)
        for event in option.status_history:
            evidence.extend(event.evidence)
        for ev in evidence:
            if ev.quote not in quotes:
                quotes.append(ev.quote)
    return "\n".join(part for part in parts + quotes if part)


def _norm_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _paths_match(stored: str, query: str) -> bool:
    """Equal, or one path ends with "/" + the other (``xLib/a.py`` does not match ``Lib/a.py``)."""
    return stored == query or stored.endswith("/" + query) or query.endswith("/" + stored)


def _window(text: str, tokens: list[str], width: int = SNIPPET_CHARS) -> str:
    """About ``width`` characters on each side of the first token found in ``text``."""
    lower = text.lower()
    found = [lower.find(token) for token in tokens if token in lower]
    at = min(found) if found else 0
    start, end = max(0, at - width), min(len(text), at + width)
    snippet = " ".join(text[start:end].split())
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def _post_from_row(row: sqlite3.Row) -> Post:
    return Post(
        id=row["id"],
        source_id=row["source_id"],
        source_post_number=row["source_post_number"],
        seq=row["seq"],
        version=row["version"],
        author=row["author"],
        role=row["role"],
        created_at=row["created_at"],
        reply_to=row["reply_to"],
        quotes=json.loads(row["quotes_json"]),
        url=row["url"],
        text=row["text"],
        sentences=json.loads(row["sentences_json"]),
        spans=json.loads(row["spans_json"]),
        sha256=row["sha256"],
        meta=json.loads(row["meta_json"]),
    )


def _link_from_row(row: sqlite3.Row) -> CodeLink:
    return CodeLink(
        repo=row["repo"],
        path=row["path"],
        commit=row["commit_sha"],
        pr=row["pr"],
        method=row["method"],
        strength=row["strength"],
    )


def _link_key(row: sqlite3.Row) -> tuple:
    return (row["decision_id"], row["repo"], row["path"], row["commit_sha"], row["pr"], row["method"], row["strength"])




class Store:
    """All DecRack state in one SQLite file (``":memory:"`` works too)."""

    def __init__(self, path: str | Path = DEFAULT_DB, use_fts: bool | None = None) -> None:
        """Open or create the database. ``use_fts``: None detects FTS5, False forces LIKE search."""
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._indexed = False  # FTS5 tables exist and are kept in sync on every write
        self.fts = False  # searches use FTS5; False means the LIKE fallback
        self._init_fts(use_fts)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # FTS5 -----------------------------------------------------------------

    def _init_fts(self, use_fts: bool | None) -> None:
        # The indexes are maintained whenever FTS5 works, even when use_fts=False, so
        # a database written in fallback mode still searches correctly later.
        existed = self._has_table("decisions_fts") and self._has_table("posts_fts")
        try:
            self._conn.executescript(FTS_SCHEMA)
            self._conn.execute("SELECT count(*) FROM decisions_fts").fetchone()
            self._indexed = True
        except sqlite3.OperationalError as exc:
            log.info("SQLite FTS5 is unavailable (%s); using LIKE search", exc)
            self._indexed = False
        if self._indexed and not existed:
            self._rebuild_fts()
        self.fts = self._indexed and use_fts is not False

    def _has_table(self, name: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone()
        return row is not None

    def _rebuild_fts(self) -> None:
        """Fill freshly created FTS5 tables from rows written before they existed."""
        with self._conn:
            self._conn.execute("DELETE FROM decisions_fts")
            self._conn.execute("DELETE FROM posts_fts")
            for row in self._conn.execute("SELECT id, record_json FROM decisions").fetchall():
                record = DecisionRecord.model_validate_json(row["record_json"])
                self._conn.execute(
                    "INSERT INTO decisions_fts (decision_id, body) VALUES (?, ?)", (row["id"], _record_body(record))
                )
            self._conn.execute("INSERT INTO posts_fts (post_id, thread_id, text) SELECT id, thread_id, text FROM posts")

    # Threads ----------------------------------------------------------------

    def save_thread(self, thread: Thread) -> None:
        """Insert or update a thread, replace all of its posts, and record every post version, in one transaction.

        ``post_versions`` gains a row for each (post id, version, sha256) not seen before.
        A text saved again (same hash, so the same text) is re-stamped as the latest fetch.
        """
        data = thread.model_dump(mode="json")
        fetched_at = _now()
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO threads (id, kind, url, title, meta_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                (thread.id, thread.kind, thread.url, thread.title, _dumps(data["meta"]), fetched_at),
            )
            self._conn.execute("DELETE FROM posts WHERE thread_id = ?", (thread.id,))
            if self._indexed:
                self._conn.execute("DELETE FROM posts_fts WHERE thread_id = ?", (thread.id,))
            for post in data["posts"]:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO posts (id, thread_id, source_id, source_post_number, seq, version,"
                    " author, role, created_at, reply_to, quotes_json, url, text, sentences_json, spans_json,"
                    " sha256, meta_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        post["id"],
                        thread.id,
                        post["source_id"],
                        post["source_post_number"],
                        post["seq"],
                        post["version"],
                        post["author"],
                        post["role"],
                        post["created_at"],
                        post["reply_to"],
                        _dumps(post["quotes"]),
                        post["url"],
                        post["text"],
                        _dumps(post["sentences"]),
                        _dumps(post["spans"]),
                        post["sha256"],
                        _dumps(post["meta"]),
                    ),
                )
                if self._indexed and cursor.rowcount == 1:
                    self._conn.execute(
                        "INSERT INTO posts_fts (post_id, thread_id, text) VALUES (?, ?, ?)",
                        (post["id"], thread.id, post["text"]),
                    )
                # REPLACE re-inserts the same text under a new rowid: the newest rowid is the latest fetch.
                self._conn.execute(
                    "INSERT OR REPLACE INTO post_versions (post_id, version, sha256, text, spans_json, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (post["id"], post["version"], post["sha256"], post["text"], _dumps(post["spans"]), fetched_at),
                )

    def load_thread(self, thread_id: str) -> Thread | None:
        """The stored thread with its posts in seq order, or None."""
        row = self._conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            return None
        posts = self._conn.execute("SELECT * FROM posts WHERE thread_id = ? ORDER BY seq, id", (thread_id,)).fetchall()
        return Thread(
            id=row["id"],
            kind=row["kind"],
            url=row["url"],
            title=row["title"],
            posts=[_post_from_row(post) for post in posts],
            meta=json.loads(row["meta_json"]),
        )

    def get_posts(self, thread_id: str, post_ids: list[str]) -> list[Post]:
        """The stored posts of ``thread_id`` with these ids, once each, in seq order; unknown ids are skipped."""
        wanted = list(dict.fromkeys(post_ids))
        rows: list[sqlite3.Row] = []
        for start in range(0, len(wanted), IDS_PER_QUERY):
            chunk = wanted[start : start + IDS_PER_QUERY]
            marks = ", ".join("?" for _ in chunk)
            rows += self._conn.execute(
                f"SELECT * FROM posts WHERE thread_id = ? AND id IN ({marks})", [thread_id, *chunk]
            ).fetchall()
        rows.sort(key=lambda row: (row["seq"], row["id"]))
        return [_post_from_row(row) for row in rows]

    def get_post_version(self, post_id: str, version: int, sha256: str | None = None) -> dict | None:
        """One stored text of a post version: a dict with post_id, version, sha256, text and spans, or None.

        Without ``sha256`` it is the most recently fetched text of that version (a version
        can be stored in full and leak-blanked); with ``sha256`` it is exactly that text.
        """
        query = "SELECT post_id, version, sha256, text, spans_json FROM post_versions WHERE post_id = ? AND version = ?"
        params: list[Any] = [post_id, int(version)]
        if sha256 is not None:
            query += " AND sha256 = ?"
            params.append(sha256)
        row = self._conn.execute(query + " ORDER BY rowid DESC LIMIT 1", params).fetchone()
        if row is None:
            return None
        return {
            "post_id": row["post_id"],
            "version": row["version"],
            "sha256": row["sha256"],
            "text": row["text"],
            "spans": json.loads(row["spans_json"]),
        }

    def list_threads(self) -> list[dict]:
        """One dict per thread (id, kind, url, title, posts, fetched_at), newest fetch first."""
        rows = self._conn.execute(
            "SELECT t.id, t.kind, t.url, t.title, t.fetched_at,"
            " (SELECT COUNT(*) FROM posts AS p WHERE p.thread_id = t.id) AS posts"
            " FROM threads AS t ORDER BY t.fetched_at DESC, t.id"
        ).fetchall()
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "url": row["url"],
                "title": row["title"],
                "posts": row["posts"],
                "fetched_at": row["fetched_at"],
            }
            for row in rows
        ]

    # Model calls --------------------------------------------------------------

    def get_llm_call(self, key: str) -> dict | None:
        """The recorded response for a call key, or None."""
        row = self._conn.execute("SELECT response_json FROM llm_calls WHERE key = ?", (key,)).fetchone()
        return json.loads(row["response_json"]) if row else None

    def put_llm_call(
        self,
        key: str,
        step: str,
        model: str,
        request: dict,
        response: dict,
        ms: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Record (or re-record) one model call with its request, response and costs."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO llm_calls (key, step, model, request_json, response_json, created_at,"
                " ms, tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    step,
                    model,
                    _dumps(request),
                    _dumps(response),
                    _now(),
                    int(ms or 0),
                    int(tokens_in or 0),
                    int(tokens_out or 0),
                ),
            )

    def count_llm_calls(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]

    def export_llm_calls(self, path: str | Path) -> int:
        """Write every call as a JSONL line {key, step, model, request, response}; return the count."""
        rows = self._conn.execute(
            "SELECT key, step, model, request_json, response_json FROM llm_calls ORDER BY created_at, key"
        ).fetchall()
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                line = {
                    "key": row["key"],
                    "step": row["step"],
                    "model": row["model"],
                    "request": json.loads(row["request_json"]),
                    "response": json.loads(row["response_json"]),
                }
                handle.write(_dumps(line) + "\n")
        return len(rows)

    # Decision records -----------------------------------------------------------

    def save_record(self, record: DecisionRecord) -> None:
        """Insert or replace the record for ``record.thread_id``, with its code links and index row."""
        with self._conn:
            old_ids = {
                row["id"]
                for row in self._conn.execute(
                    "SELECT id FROM decisions WHERE id = ? OR thread_id = ?", (record.id, record.thread_id)
                )
            }
            for old_id in old_ids | {record.id}:
                self._conn.execute("DELETE FROM code_links WHERE decision_id = ?", (old_id,))
                if self._indexed:
                    self._conn.execute("DELETE FROM decisions_fts WHERE decision_id = ?", (old_id,))
            self._conn.execute("DELETE FROM decisions WHERE id = ? OR thread_id = ?", (record.id, record.thread_id))
            self._conn.execute(
                "INSERT INTO decisions (id, thread_id, question, outcome, record_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (record.id, record.thread_id, record.question, record.outcome, record.model_dump_json(), _now()),
            )
            self._conn.executemany(
                "INSERT INTO code_links (decision_id, repo, path, commit_sha, pr, method, strength)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (record.id, link.repo, link.path, link.commit, link.pr, link.method, link.strength)
                    for link in record.code_links
                ],
            )
            if self._indexed:
                self._conn.execute(
                    "INSERT INTO decisions_fts (decision_id, body) VALUES (?, ?)", (record.id, _record_body(record))
                )

    def get_record(self, record_id: str) -> DecisionRecord | None:
        row = self._conn.execute("SELECT record_json FROM decisions WHERE id = ?", (record_id,)).fetchone()
        return DecisionRecord.model_validate_json(row["record_json"]) if row else None

    def record_for_thread(self, thread_id: str) -> DecisionRecord | None:
        row = self._conn.execute("SELECT record_json FROM decisions WHERE thread_id = ?", (thread_id,)).fetchone()
        return DecisionRecord.model_validate_json(row["record_json"]) if row else None

    def all_records(self) -> list[DecisionRecord]:
        """Every stored record, most recently saved first."""
        rows = self._conn.execute("SELECT record_json FROM decisions ORDER BY created_at DESC, id").fetchall()
        return [DecisionRecord.model_validate_json(row["record_json"]) for row in rows]

    def search_records(self, query: str, status: str | None = None, limit: int = 10) -> list[DecisionRecord]:
        """Records matching any word of ``query``, best first.

        With ``status``, only records that have at least one option with that status.
        """
        tokens = query_tokens(query)
        if not tokens or limit <= 0:
            return []
        if self.fts:
            rows = self._conn.execute(
                "SELECT decision_id FROM decisions_fts WHERE decisions_fts MATCH ?"
                " ORDER BY bm25(decisions_fts), decision_id",
                (_fts_query(tokens),),
            ).fetchall()
            ids = list(dict.fromkeys(row["decision_id"] for row in rows))
            candidates = [record for record in (self.get_record(i) for i in ids) if record is not None]
        else:
            hits = _like_hits("(question || ' ' || outcome || ' ' || record_json)", len(tokens))
            rows = self._conn.execute(
                f"SELECT record_json FROM (SELECT id, record_json, {hits} AS hits FROM decisions)"
                " WHERE hits > 0 ORDER BY hits DESC, id",
                [_like_pattern(token) for token in tokens],
            ).fetchall()
            candidates = [DecisionRecord.model_validate_json(row["record_json"]) for row in rows]
        found: list[DecisionRecord] = []
        for record in candidates:
            if status and not any(option.status == status for option in record.options):
                continue
            found.append(record)
            if len(found) >= limit:
                break
        return found

    def records_for_paths(self, paths: list[str]) -> list[tuple[DecisionRecord, CodeLink]]:
        """(record, link) pairs whose link path equals a query path or ends with it at a "/" (or vice versa)."""
        wanted = [path for path in (_norm_path(p) for p in paths) if path]
        if not wanted:
            return []
        rows = self._conn.execute("SELECT * FROM code_links ORDER BY rowid").fetchall()
        results: list[tuple[DecisionRecord, CodeLink]] = []
        seen: set[tuple] = set()
        cache: dict[str, DecisionRecord | None] = {}
        for query in wanted:
            for row in rows:
                key = _link_key(row)
                if key in seen or not _paths_match(_norm_path(row["path"]), query):
                    continue
                record = self._cached_record(row["decision_id"], cache)
                if record is not None:
                    seen.add(key)
                    results.append((record, _link_from_row(row)))
        return results

    def records_for_prs(self, repo: str | None, prs: list[int]) -> list[tuple[DecisionRecord, CodeLink | None]]:
        """Records linked to these PR numbers, plus records compiled from the PR threads themselves.

        A code link matches on its ``pr`` (and on ``repo`` when both sides know it); a record
        whose thread id is ``gh:{repo}#{pr}`` comes with link None unless already listed.
        """
        results: list[tuple[DecisionRecord, CodeLink | None]] = []
        seen_links: set[tuple] = set()
        cache: dict[str, DecisionRecord | None] = {}
        for pr in prs:
            rows = self._conn.execute("SELECT * FROM code_links WHERE pr = ? ORDER BY rowid", (int(pr),)).fetchall()
            for row in rows:
                if repo and row["repo"] and row["repo"].lower() != repo.lower():
                    continue
                key = _link_key(row)
                if key in seen_links:
                    continue
                record = self._cached_record(row["decision_id"], cache)
                if record is not None:
                    seen_links.add(key)
                    results.append((record, _link_from_row(row)))
            if not repo:
                continue
            row = self._conn.execute(
                "SELECT id FROM decisions WHERE thread_id = ? COLLATE NOCASE", (f"gh:{repo}#{int(pr)}",)
            ).fetchone()
            if row is not None and all(listed.id != row["id"] for listed, _ in results):
                record = self._cached_record(row["id"], cache)
                if record is not None:
                    results.append((record, None))
        return results

    def _cached_record(self, record_id: str, cache: dict[str, DecisionRecord | None]) -> DecisionRecord | None:
        if record_id not in cache:
            cache[record_id] = self.get_record(record_id)
        return cache[record_id]

    def search_posts(self, query: str, limit: int = 10) -> list[dict]:
        """Posts matching any word of ``query``, best first, each with a short snippet.

        Each row has post_id, thread_id, seq, author, url and snippet.
        """
        tokens = query_tokens(query)
        if not tokens or limit <= 0:
            return []
        if self.fts:
            rows = self._conn.execute(
                f"SELECT post_id, thread_id, snippet(posts_fts, 2, '', '', '…', {SNIPPET_TOKENS}) AS snippet"
                " FROM posts_fts WHERE posts_fts MATCH ? ORDER BY bm25(posts_fts), thread_id, post_id LIMIT ?",
                (_fts_query(tokens), limit),
            ).fetchall()
            matches = [(row["post_id"], row["thread_id"], row["snippet"]) for row in rows]
        else:
            hits = _like_hits("text", len(tokens))
            rows = self._conn.execute(
                f"SELECT id, thread_id, text FROM (SELECT id, thread_id, seq, text, {hits} AS hits FROM posts)"
                " WHERE hits > 0 ORDER BY hits DESC, thread_id, seq LIMIT ?",
                [*(_like_pattern(token) for token in tokens), limit],
            ).fetchall()
            matches = [(row["id"], row["thread_id"], _window(row["text"], tokens)) for row in rows]
        results: list[dict] = []
        for post_id, thread_id, snippet in matches:
            post = self._conn.execute(
                "SELECT seq, author, url FROM posts WHERE thread_id = ? AND id = ?", (thread_id, post_id)
            ).fetchone()
            if post is None:
                continue
            results.append(
                {
                    "post_id": post_id,
                    "thread_id": thread_id,
                    "seq": post["seq"],
                    "author": post["author"],
                    "url": post["url"],
                    "snippet": " ".join(snippet.split()),
                }
            )
        return results
