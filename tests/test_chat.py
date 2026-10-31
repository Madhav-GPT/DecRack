"""decrack chat: input parsing, model auto-detect, scope, cards and the cited answer step. All offline."""

from __future__ import annotations

import httpx
import pytest

from decrack import chat, preflight
from decrack.chat import NO_MATCH, SCOPE, ChatSession, build_cards, parse_line, run_chat
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


def test_no_link_gives_the_scope(session):
    assert session.handle("what is the weather like?") == [SCOPE]
    assert SCOPE in session.handle("/help")


def test_answer_cites_card_numbers(session):
    lines = session.handle("pep:9999 why not a decorator?")
    assert lines[0].startswith("Read 1 thread(s):")
    assert lines[1].startswith("[1] Use a decorator instead of a new keyword | rejected (confirmed)")
    assert "Answer (scripted, from cited evidence):" in lines
    sources = lines[lines.index("Sources:") + 1 :]
    assert sources == [f"[2] {THREAD_URL}/4"]  # 9 is not a card; the repeated 2 counts once
    assert session.last_source == "pep:9999"

    follow_up = session.handle("and the global flag?")  # reuses the remembered link
    assert follow_up[0].startswith("Read 1 thread(s):")


def test_no_matching_record_makes_no_model_call(session):
    lines = session.handle("pep:9999 zebra quantum")
    assert lines[-2:] == [NO_MATCH, SCOPE]
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
    assert any(line.startswith("Commands:") for line in lines)
