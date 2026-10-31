"""decrack chat: input parsing, model auto-detect, scope, cards and the cited answer step. All offline."""

from __future__ import annotations

import httpx
import pytest

from decrack import chat, preflight
from decrack.chat import (
    EXAMPLE,
    NO_LINK,
    NO_MATCH,
    NO_MATCH_HINT,
    SCOPE,
    ChatSession,
    build_cards,
    parse_line,
    run_chat,
)
from decrack.config import DEFAULT_MODEL, Settings
from decrack.pipeline.llm import ScriptedLLM

THREAD_URL = "https://discuss.python.org/t/pep-9999-lazy-widgets/99999"


def tags_client(names: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": name} for name in names]})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def session(tmp_path, store, synthetic_thread, sample_record):
    def refuse():
        raise AssertionError("no search in these tests")

    reply = {"answer": "Decorators cannot apply to imports.", "cites": [2, 9, 2]}
    llm = ScriptedLLM({"answer": lambda messages: reply})
    return ChatSession(
        Settings(db_path=str(tmp_path / "decrack.db")),
        store,
        llm,
        "scripted",
        loader=lambda ref, settings=None, client=None: synthetic_thread,
        compiler=lambda thread, llm, settings, progress=None: sample_record,
        client_factory=refuse,
    )


def test_parse_line():
    repo = parse_line("https://github.com/python/cpython why not a decorator?")
    assert (repo.source, repo.question) == ("https://github.com/python/cpython", "why not a decorator?")
    issue = parse_line("why was it closed? https://github.com/o/r/issues/12.")
    assert (issue.source, issue.question) == ("https://github.com/o/r/issues/12", "why was it closed?")
    assert parse_line("PEP:830 why timestamps?").source == "pep:830"
    assert parse_line("see https://discuss.python.org/t/pep-830/106942 please").source == (
        "https://discuss.python.org/t/pep-830/106942"
    )
    command = parse_line("/show dr-1a2b3c4d")
    assert (command.command, command.argument) == ("/show", "dr-1a2b3c4d")
    plain = parse_line("  what is   the weather?  ")
    assert (plain.command, plain.source, plain.question) == (None, None, "what is the weather?")


def test_parse_line_accepts_shorthand_and_links_without_https():
    short = parse_line("Why didn’t uv add pip’s --user flag? astral-sh/uv#2077")
    assert (short.source, short.question) == ("astral-sh/uv#2077", "Why didn’t uv add pip’s --user flag?")
    bare = parse_line("github.com/astral-sh/uv/issues/2077 why not --user?")
    assert bare.source == "https://github.com/astral-sh/uv/issues/2077"
    assert parse_line("www.github.com/psf/black why no isort?").source == "https://github.com/psf/black"
    assert parse_line("discuss.python.org/t/105519 what about d-strings?").source == (
        "https://discuss.python.org/t/105519"
    )


def test_links_stop_at_quotes_and_only_pep_n_is_a_pep():
    quoted = parse_line("What was decided? “https://discuss.python.org/t/105519”")
    assert quoted.source == "https://discuss.python.org/t/105519"
    assert parse_line("What’s “pepy-tech/pepy#12” about?").source == "pepy-tech/pepy#12"
    assert parse_line("why ‘pep: 830’?").source == "pep:830"


def test_pick_model_prefers_the_configured_then_the_default_then_any_local():
    assert preflight.pick_model(Settings(model="test-model:b"), tags_client([DEFAULT_MODEL, "test-model:b"])) == (
        "test-model:b"
    )
    assert preflight.pick_model(Settings(model="test-model:c"), tags_client([DEFAULT_MODEL])) == DEFAULT_MODEL
    assert preflight.pick_model(Settings(), tags_client(["big:cloud", "test-model:b"])) == "test-model:b"
    assert preflight.using_line("test-model:b") == "Using test-model:b (local, open-weight via Ollama)"


def test_pick_model_gates():
    with pytest.raises(preflight.GateError) as info:
        preflight.pick_model(Settings(), tags_client(["big:cloud"]))
    assert (info.value.error, info.value.code) == (preflight.NO_MODEL, 3)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(preflight.GateError) as info:
        preflight.pick_model(Settings(), httpx.Client(transport=httpx.MockTransport(down)))
    assert info.value.error == preflight.OLLAMA_DOWN


def test_no_link_asks_for_one(session):
    assert session.handle("what is the weather like?") == [NO_LINK, EXAMPLE]
    assert session.handle("Why didn’t uv add pip’s “--user” flag?") == [NO_LINK, EXAMPLE]
    assert SCOPE in session.handle("/help")


def test_answer_cites_card_numbers(session):
    lines = session.handle("pep:9999 why not a decorator?")
    assert lines[0].startswith("Read 1 thread(s):")
    assert lines[1] == "[1] Use a decorator instead of a new keyword"
    assert lines[2] == "    status: rejected (confirmed)"
    assert "Answer (scripted, from cited evidence):" in lines
    sources = [line for line in lines[lines.index("Sources:") + 1 :] if line.startswith("[")]
    assert sources == [f"[2] {THREAD_URL}/4"]  # 9 is not a card; the repeated 2 counts once
    assert lines[-1].startswith("Tip: /show ")
    assert session.last_source == "pep:9999"

    follow_up = session.handle("and the global flag?")  # reuses the remembered link
    assert follow_up[0].startswith("Read 1 thread(s):")


def test_no_matching_record_makes_no_model_call(session):
    lines = session.handle("pep:9999 zebra quantum")
    assert lines[-2:] == [NO_MATCH, NO_MATCH_HINT]
    assert [step for step, _ in session.llm.requests if step == "answer"] == []


def test_build_cards_puts_rejected_options_first(sample_record):
    cards = build_cards([(sample_record, "text match")])
    assert [card.status for card in cards] == ["rejected", "rejected", "rejected", "accepted"]
    assert [card.number for card in cards] == [1, 2, 3, 4]


def test_run_chat_greets_with_the_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "make_llm", lambda settings, store=None: ScriptedLLM({}))
    lines: list[str] = []
    inputs = iter(["/help", "/quit"])
    settings = Settings(db_path=str(tmp_path / "t.db"))
    code = run_chat(settings, input_fn=lambda prompt: next(inputs), print_fn=lines.append)
    assert code == 0
    assert lines[0] == SCOPE
    assert lines[1] == EXAMPLE
    assert any(line.startswith("Commands:") for line in lines)


def test_maintainer_statements_quote_the_deciders(store, synthetic_thread, sample_record):
    thread = synthetic_thread.model_copy(deep=True)
    post = thread.posts[-1]
    post.role = "decider"
    post.sentences = [
        "> quoted words from someone else should be skipped entirely here.",
        "We don't think a decorator is the right way to do that.",
    ]
    store.save_thread(thread)
    record = sample_record.model_copy(update={"thread_id": thread.id})
    lines = chat.maintainer_statements(store, [record], "why not a decorator?")
    assert lines and "We don't think a decorator" in lines[0]
    assert all("quoted words" not in line for line in lines)


def test_cards_do_not_repeat_a_quote_or_show_template_reasons(sample_record):
    cards = build_cards([(sample_record, "text match")])
    quotes = [card.quote for card in cards if card.quote]
    assert len(quotes) == len(set(quotes)) or len(set(quotes)) == 1
    assert all("adopted, turned down" not in card.reason for card in cards)


def test_styler_is_plain_without_a_terminal():
    assert chat.styler(False)("    status: rejected (confirmed)") == "    status: rejected (confirmed)"
    assert "\033[" in chat.styler(True)("    status: rejected (confirmed)")
