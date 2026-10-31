"""Tests for decrack.store: threads, post versions, model calls, records, search and code links."""

from __future__ import annotations

import json

import pytest

from decrack.models import CodeLink, DecisionRecord, Evidence, Option, make_record_id
from decrack.store import Store
from decrack.text import finalize_post, sha256_text

OTHER_THREAD = "gh:example/widgets#7"
OTHER_URL = "https://github.com/example/widgets/issues/7"
OTHER_QUOTE = "Caching rendered output saves time."


def make_other_record() -> DecisionRecord:
    """A second, unrelated record: one accepted option, cited from the issue body, and a link without a PR."""
    return DecisionRecord(
        id=make_record_id(OTHER_THREAD),
        thread_id=OTHER_THREAD,
        thread_url=OTHER_URL,
        question="Should widgets cache rendered output?",
        outcome="1 option: 1 accepted",
        options=[
            Option(
                key="A1",
                title="Cache rendered output in memory",
                status="accepted",
                evidence=[
                    Evidence(
                        post_id=OTHER_THREAD,  # an issue body has the issue's own id
                        post_version=1,
                        post_sha256=sha256_text(OTHER_QUOTE),
                        sentence_indexes=[1],
                        start=0,
                        end=len(OTHER_QUOTE),
                        quote=OTHER_QUOTE,
                        url=OTHER_URL,
                        author="gina",
                    )
                ],
            )
        ],
        code_links=[CodeLink(repo="example/widgets", path="Lib/cache.py", method="mentioned", strength="direct")],
    )


def ids(records: list[DecisionRecord]) -> list[str]:
    return [record.id for record in records]


def spans_of(post) -> list[dict]:
    return [span.model_dump() for span in post.spans]


# Threads ----------------------------------------------------------------------


def test_thread_round_trip(store, synthetic_thread):
    first, second, third = synthetic_thread.posts[:3]
    third.quotes = [first.id, second.id]
    second.meta["extra"] = {"nested": [1, 2], "note": "héllo"}
    store.save_thread(synthetic_thread)

    loaded = store.load_thread("pep:9999")
    assert loaded is not None
    assert loaded == synthetic_thread
    assert [post.seq for post in loaded.posts] == list(range(1, 9))
    post = loaded.posts[2]
    assert post.id == "dpo:99999:1003"
    assert post.source_id == "dpo:t99999"
    assert post.source_post_number == 3
    assert post.version == 1
    assert post.reply_to == "dpo:99999:1001"
    assert post.quotes == ["dpo:99999:1001", "dpo:99999:1002"]
    assert post.spans == third.spans
    assert post.spans[1].start == len(post.sentences[0]) + 1
    assert post.text[post.spans[1].start : post.spans[1].end] == post.sentences[1]
    assert loaded.posts[0].reply_to is None
    assert loaded.posts[0].created_at == first.created_at
    assert loaded.posts[0].created_at.tzinfo is not None
    assert loaded.posts[1].meta["extra"] == {"nested": [1, 2], "note": "héllo"}
    assert loaded.posts[7].meta["flair_name"] == "steering-council"
    assert loaded.posts[4].sha256 == synthetic_thread.posts[4].sha256
    assert loaded.meta == {
        "created_by": ["alice"],
        "topic_ids": [99999],
        "forum": "https://discuss.python.org",
        "pep": 9999,
    }
    assert store.load_thread("pep:1") is None


def test_save_thread_replaces_posts(store, synthetic_thread):
    store.save_thread(synthetic_thread)
    assert store.search_posts("soft")

    shorter = synthetic_thread.model_copy(update={"posts": synthetic_thread.posts[:3], "title": "Renamed"})
    store.save_thread(shorter)

    loaded = store.load_thread("pep:9999")
    assert loaded.title == "Renamed"
    assert [post.seq for post in loaded.posts] == [1, 2, 3]
    # Posts 7 and 8 were the only ones about the soft keyword; their index rows went with them.
    assert store.search_posts("soft") == []
    assert len(store.list_threads()) == 1
    # Their texts stay in post_versions, so old citations of them still resolve.
    last = synthetic_thread.posts[7]
    assert store.get_post_version(last.id, 1)["text"] == last.text


def test_get_posts(store, synthetic_thread):
    store.save_thread(synthetic_thread)
    post_ids = [post.id for post in synthetic_thread.posts]

    found = store.get_posts("pep:9999", [post_ids[6], post_ids[1], "dpo:99999:1", post_ids[1]])
    # In thread order, each once; an unknown id is skipped.
    assert [post.id for post in found] == [post_ids[1], post_ids[6]]
    assert found[0] == synthetic_thread.posts[1]
    assert found[1] == synthetic_thread.posts[6]
    assert store.get_posts("pep:9999", []) == []
    assert store.get_posts("pep:1", post_ids) == []


# Post versions ------------------------------------------------------------------


def test_post_versions_keep_the_old_version(store, synthetic_thread):
    store.save_thread(synthetic_thread)
    post = synthetic_thread.posts[4]
    old_text, old_sha, old_spans = post.text, post.sha256, spans_of(post)
    assert store.get_post_version(post.id, 1) == {
        "post_id": post.id,
        "version": 1,
        "sha256": old_sha,
        "text": old_text,
        "spans": old_spans,
    }

    # The author edits the post: Discourse bumps its version.
    post.text = old_text.replace("rejected", "turned down")
    finalize_post(post)
    post.version = 2
    store.save_thread(synthetic_thread)

    assert store.get_post_version(post.id, 1) == {
        "post_id": post.id,
        "version": 1,
        "sha256": old_sha,
        "text": old_text,
        "spans": old_spans,
    }
    edited = store.get_post_version(post.id, 2)
    assert edited == {
        "post_id": post.id,
        "version": 2,
        "sha256": post.sha256,
        "text": post.text,
        "spans": spans_of(post),
    }
    assert edited["sha256"] != old_sha
    assert "turned down" in edited["text"]
    current = store.load_thread("pep:9999").posts[4]
    assert (current.version, current.text) == (2, post.text)
    assert store.get_post_version(post.id, 3) is None
    assert store.get_post_version("dpo:99999:1", 1) is None


def test_post_versions_keep_a_blanked_copy_apart(store, synthetic_thread):
    """The leak guard blanks a post but keeps its id and version, so the hash tells the two texts apart."""
    opening = synthetic_thread.posts[0]
    full_text, full_sha = opening.text, opening.sha256
    store.save_thread(synthetic_thread)

    blanked = synthetic_thread.model_copy(deep=True)
    blanked.posts[0].text = ""
    finalize_post(blanked.posts[0])
    store.save_thread(blanked)

    # Without a hash: the most recently fetched text of that version.
    assert store.get_post_version(opening.id, 1) == {
        "post_id": opening.id,
        "version": 1,
        "sha256": sha256_text(""),
        "text": "",
        "spans": [],
    }
    # With a hash: exactly that text, so the full copy is still there.
    full = store.get_post_version(opening.id, 1, sha256=full_sha)
    assert full["text"] == full_text
    assert full["spans"] == spans_of(opening)
    assert store.get_post_version(opening.id, 1, sha256="0" * 64) is None

    # Fetching the full post again makes it the latest once more.
    store.save_thread(synthetic_thread)
    assert store.get_post_version(opening.id, 1)["text"] == full_text
    assert store.get_post_version(opening.id, 1, sha256=sha256_text(""))["text"] == ""


def test_list_threads(store, synthetic_thread):
    assert store.list_threads() == []
    store.save_thread(synthetic_thread)
    rows = store.list_threads()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"id", "kind", "url", "title", "posts", "fetched_at"}
    assert row["id"] == "pep:9999"
    assert row["kind"] == "discourse"
    assert row["url"] == synthetic_thread.url
    assert row["title"] == "PEP 9999: Lazy widgets"
    assert row["posts"] == 8
    assert row["fetched_at"]


def test_memory_store_as_context_manager(synthetic_thread):
    with Store(":memory:") as db:
        db.save_thread(synthetic_thread)
        assert db.load_thread("pep:9999") is not None


# Model calls ------------------------------------------------------------------


def test_llm_calls_put_get_count_export(store, tmp_path):
    request = {"model": "m", "step": "map", "messages": [{"role": "user", "content": "héllo"}]}
    assert store.get_llm_call("k1") is None
    assert store.count_llm_calls() == 0

    store.put_llm_call("k1", "map", "m", request, {"items": []}, ms=12, tokens_in=5, tokens_out=3)
    store.put_llm_call("k2", "merge", "m", {"step": "merge"}, {"groups": [["A1", "A2"]]})
    store.put_llm_call("k1", "map", "m", request, {"items": [{"alt_ref": "new"}]})

    assert store.count_llm_calls() == 2
    assert store.get_llm_call("k1") == {"items": [{"alt_ref": "new"}]}
    assert store.get_llm_call("k2") == {"groups": [["A1", "A2"]]}

    out = tmp_path / "nested" / "calls.jsonl"
    assert store.export_llm_calls(out) == 2
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rows = {row["key"]: row for row in map(json.loads, lines)}
    assert set(rows) == {"k1", "k2"}
    for row in rows.values():
        assert set(row) == {"key", "step", "model", "request", "response"}
    assert rows["k1"]["request"] == request
    assert rows["k1"]["step"] == "map"
    assert rows["k1"]["response"] == {"items": [{"alt_ref": "new"}]}
    assert rows["k2"]["model"] == "m"


# Records ----------------------------------------------------------------------


def test_record_save_and_get(store, sample_record):
    store.save_record(sample_record)
    assert store.get_record(sample_record.id) == sample_record
    assert store.record_for_thread("pep:9999") == sample_record
    assert store.get_record("dr-00000000") is None
    assert store.record_for_thread("pep:1") is None
    assert ids(store.all_records()) == [sample_record.id]

    other = make_other_record()
    store.save_record(other)
    assert set(ids(store.all_records())) == {sample_record.id, other.id}


def test_record_upsert_by_thread(store, sample_record):
    store.save_record(sample_record)
    changed = sample_record.model_copy(
        update={"outcome": "changed outcome", "code_links": sample_record.code_links[:1]}
    )
    store.save_record(changed)
    assert ids(store.all_records()) == [sample_record.id]
    assert store.get_record(sample_record.id).outcome == "changed outcome"
    # The PR 42 link was dropped with the old code links.
    assert store.records_for_prs("example/widgets", [42]) == []

    renamed = sample_record.model_copy(update={"id": "dr-0000beef"})
    store.save_record(renamed)
    assert ids(store.all_records()) == ["dr-0000beef"]
    assert store.get_record(sample_record.id) is None
    assert store.record_for_thread("pep:9999").id == "dr-0000beef"


# Search -----------------------------------------------------------------------


@pytest.fixture(params=[None, False], ids=["auto", "like"])
def search_store(request, tmp_path, sample_record):
    db = Store(tmp_path / "search.db", use_fts=request.param)
    db.save_record(sample_record)
    db.save_record(make_other_record())
    yield db
    db.close()


def test_search_records(search_store, sample_record):
    other_id = make_record_id(OTHER_THREAD)
    assert ids(search_store.search_records("decorator")) == [sample_record.id]
    assert ids(search_store.search_records("Decorators")) == [sample_record.id]
    assert ids(search_store.search_records("caching")) == [other_id]
    assert set(ids(search_store.search_records("widgets"))) == {sample_record.id, other_id}
    assert len(search_store.search_records("widgets", limit=1)) == 1
    assert search_store.search_records("zeppelin") == []


def test_search_records_status_filter(search_store, sample_record):
    other_id = make_record_id(OTHER_THREAD)
    assert ids(search_store.search_records("widgets", status="rejected")) == [sample_record.id]
    assert set(ids(search_store.search_records("widgets", status="accepted"))) == {sample_record.id, other_id}
    assert search_store.search_records("widgets", status="withdrawn") == []


def test_search_records_empty_query(search_store):
    assert search_store.search_records("") == []
    assert search_store.search_records("   ?! ") == []


def test_like_fallback_ranks_by_matching_words(tmp_path, sample_record):
    with Store(tmp_path / "like.db", use_fts=False) as db:
        assert db.fts is False
        db.save_record(make_other_record())
        db.save_record(sample_record)
        found = db.search_records("decorator widgets")
        assert ids(found) == [sample_record.id, make_record_id(OTHER_THREAD)]


def test_index_follows_writes_made_in_fallback_mode(tmp_path, sample_record):
    path = tmp_path / "mixed.db"
    with Store(path, use_fts=False) as db:
        db.save_record(sample_record)
    with Store(path) as db:
        assert ids(db.search_records("decorator")) == [sample_record.id]


@pytest.mark.parametrize("use_fts", [None, False], ids=["auto", "like"])
def test_search_posts(tmp_path, synthetic_thread, use_fts):
    with Store(tmp_path / "posts.db", use_fts=use_fts) as db:
        db.save_thread(synthetic_thread)
        second, fifth = synthetic_thread.posts[1], synthetic_thread.posts[4]
        hits = db.search_posts("decorator approach")
        assert hits
        assert {second.id, fifth.id} <= {hit["post_id"] for hit in hits}
        hit = next(hit for hit in hits if hit["post_id"] == fifth.id)
        assert set(hit) == {"post_id", "thread_id", "seq", "author", "url", "snippet"}
        assert hit["thread_id"] == "pep:9999"
        assert hit["seq"] == 5
        assert hit["author"] == "alice"
        assert hit["url"] == fifth.url
        assert "decorator" in hit["snippet"].lower()
        assert len(db.search_posts("keyword", limit=2)) == 2
        assert db.search_posts("zeppelin") == []
        assert db.search_posts("") == []


# Code links -------------------------------------------------------------------


def test_records_for_paths(store, sample_record):
    store.save_record(sample_record)
    other = make_other_record()
    store.save_record(other)

    def found(paths):
        return [(record.id, link.path) for record, link in store.records_for_paths(paths)]

    widgets = [(sample_record.id, "Lib/widgets.py")]
    assert found(["Lib/widgets.py"]) == widgets
    assert found(["widgets.py"]) == widgets
    assert found(["./Lib/widgets.py"]) == widgets
    assert found(["Lib\\widgets.py"]) == widgets
    assert found(["/home/dev/widgets/Lib/widgets.py"]) == widgets
    assert found(["Lib/widgets.py", "widgets.py"]) == widgets
    assert found(["xLib/widgets.py"]) == []
    assert found(["Lib/missing.py"]) == []
    assert found([]) == []
    assert found(["Lib/lazy.py", "Lib/cache.py"]) == [(sample_record.id, "Lib/lazy.py"), (other.id, "Lib/cache.py")]

    record, link = store.records_for_paths(["Lib/lazy.py"])[0]
    assert record == sample_record
    assert link == CodeLink(repo="example/widgets", path="Lib/lazy.py", pr=42, method="pr_files", strength="historical")
    _, widgets_link = store.records_for_paths(["Lib/widgets.py"])[0]
    assert (widgets_link.method, widgets_link.strength) == ("mentioned", "direct")


def test_records_for_prs(store, sample_record):
    store.save_record(sample_record)
    other = make_other_record()
    store.save_record(other)

    def found(repo, prs):
        return [(record.id, link.path if link else None) for record, link in store.records_for_prs(repo, prs)]

    assert found("example/widgets", [42]) == [(sample_record.id, "Lib/lazy.py")]
    assert found(None, [42]) == [(sample_record.id, "Lib/lazy.py")]
    assert found("someone/else", [42]) == []
    # The other record was compiled from issue #7's own thread, so it comes without a link.
    assert found("example/widgets", [7]) == [(other.id, None)]
    assert found("example/widgets", [42, 7]) == [(sample_record.id, "Lib/lazy.py"), (other.id, None)]
    assert found("example/widgets", [999]) == []
    assert found(None, []) == []
