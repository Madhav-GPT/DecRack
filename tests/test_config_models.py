"""Tests for the shared contracts (models.py) and settings (config.py)."""

from __future__ import annotations

import json

from decrack.config import DEFAULT_MODEL, DEFAULT_OLLAMA_HOST, Settings, load_settings
from decrack.models import SCHEMA_VERSION, DecisionRecord, Thread, make_record_id, parse_alias, sentence_alias


def test_sentence_aliases_round_trip():
    assert sentence_alias(12, 3) == "p12.s3"
    assert parse_alias("p12.s3") == (12, 3)
    assert parse_alias(" p1.s10 ") == (1, 10)
    assert parse_alias("p12") is None
    assert parse_alias("12.3") is None


def test_record_id_is_deterministic():
    first = make_record_id("pep:830")
    assert first == make_record_id("pep:830")
    assert first != make_record_id("pep:831")
    assert first.startswith("dr-") and len(first) == 11


def test_thread_and_record_json_round_trip(synthetic_thread, sample_record):
    thread = Thread.model_validate(json.loads(json.dumps(synthetic_thread.model_dump(mode="json"))))
    assert thread == synthetic_thread
    assert thread.post_by_seq(5).author == "alice"
    assert thread.post_by_id("dpo:99999:1005").seq == 5
    assert thread.post_by_seq(99) is None and thread.post_by_id("missing") is None
    record = DecisionRecord.model_validate(json.loads(json.dumps(sample_record.model_dump(mode="json"))))
    assert record == sample_record
    assert record.run.schema_version == SCHEMA_VERSION


def test_synthetic_spans_slice_the_sentences(synthetic_thread):
    for post in synthetic_thread.posts:
        assert [post.text[span.start : span.end] for span in post.spans] == post.sentences
        assert [span.index for span in post.spans] == list(range(1, len(post.sentences) + 1))


def test_sample_evidence_quotes_are_exact_slices(synthetic_thread, sample_record):
    for option in sample_record.options:
        items = list(option.evidence) + [ev for reason in option.reasons for ev in reason.evidence]
        for event in option.status_history:
            items.extend(event.evidence)
        for ev in items:
            post = synthetic_thread.post_by_id(ev.post_id)
            assert post is not None and post.text[ev.start : ev.end] == ev.quote
            assert ev.post_sha256 == post.sha256 and ev.post_version == post.version


def test_default_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECRACK_LLM", raising=False)
    monkeypatch.delenv("DECRACK_DB", raising=False)
    settings = load_settings()
    assert settings.model == DEFAULT_MODEL
    assert settings.ollama_host == DEFAULT_OLLAMA_HOST == "http://127.0.0.1:11434"
    assert settings.llm_mode == "ollama"
    assert settings.num_ctx == 32768
    assert settings.window_max_tokens == 6000 and settings.window_overlap_tokens == 800
    assert settings.support_check is True and settings.support_batch_size == 8


def test_precedence_toml_then_env_then_flags(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "decrack.toml").write_text(
        '[decrack]\nmodel = "gemma4:e4b"\ndb_path = "from-toml.db"\nwindow_max_tokens = 4000\n'
        'support_check = false\nollama_host = "http://10.0.0.5:11434"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DECRACK_DB", "from-env.db")
    monkeypatch.setenv("DECRACK_LLM", "replay")

    settings = load_settings()
    assert settings.model == "gemma4:e4b"
    assert settings.window_max_tokens == 4000
    assert settings.support_check is False
    assert settings.db_path == "from-env.db"
    assert settings.llm_mode == "replay"
    # The Ollama host can only change through the CLI flag.
    assert settings.ollama_host == DEFAULT_OLLAMA_HOST

    flagged = load_settings(db="flag.db", model="qwen3.5:9b", ollama_host="http://192.168.1.20:11434/")
    assert flagged.db_path == "flag.db"
    assert flagged.model == "qwen3.5:9b"
    assert flagged.ollama_host == "http://192.168.1.20:11434"


def test_unknown_llm_mode_is_ignored(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DECRACK_LLM", "something-else")
    assert load_settings().llm_mode == "ollama"


def test_settings_copy_for_eval_mode():
    settings = Settings()
    eval_settings = settings.model_copy(update={"eval_mode": True})
    assert eval_settings.eval_mode and not settings.eval_mode
