"""MCP server: registered tools and prompt, and the tool functions against a stored record."""

import asyncio
import json

import pytest

pytest.importorskip("mcp")

import decrack.mcp_server as mcp_server  # noqa: E402
from decrack import preflight  # noqa: E402
from decrack.ask import ASK_HELP  # noqa: E402
from decrack.config import Settings  # noqa: E402
from decrack.mcp_server import (  # noqa: E402
    INSTRUCTIONS,
    PROMPT_NAMES,
    TOOL_NAMES,
    build_server,
    main,
    review_prompt,
    self_check,
    tool_ask,
    tool_check_change,
    tool_decisions_for_files,
    tool_get_decision,
    tool_search_decisions,
    tool_search_evidence,
)
from decrack.models import make_record_id  # noqa: E402
from decrack.pipeline.llm import ScriptedLLM  # noqa: E402
from decrack.search import NOTICE  # noqa: E402

DECORATOR_QUOTE = "We rejected the decorator approach because decorators cannot apply to import statements."


def names(result, attr: str) -> set[str]:
    return {item.name for item in getattr(result, attr, result)}


def flatten(result) -> str:
    """All text in a call_tool result, whatever container the SDK returns it in."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result)
    if isinstance(result, (list, tuple)):
        return "\n".join(flatten(item) for item in result)
    parts = [getattr(result, "text", "") or ""]
    for attr in ("content", "structured_content"):
        value = getattr(result, attr, None)
        if value is not None:
            parts.append(flatten(value))
    return "\n".join(parts)


@pytest.fixture
def settings(tmp_path, store, synthetic_thread, sample_record) -> Settings:
    # The conftest store fixture writes tmp_path / "decrack.db"; the tools open their own Store on it.
    store.save_thread(synthetic_thread)
    store.save_record(sample_record)
    return Settings(db_path=str(tmp_path / "decrack.db"))


def test_tools_and_prompt_registered(settings):
    # ask runs the local model; every other tool only reads.
    assert TOOL_NAMES == (
        "ask",
        "search_decisions",
        "get_decision",
        "decisions_for_files",
        "check_change",
        "search_evidence",
    )
    assert "`decrack run <ref>`" in INSTRUCTIONS
    assert "job_status" not in INSTRUCTIONS
    server = build_server(settings)
    assert names(asyncio.run(server.list_tools()), "tools") == set(TOOL_NAMES)
    assert names(asyncio.run(server.list_prompts()), "prompts") == set(PROMPT_NAMES)


def test_self_check(capsys):
    assert self_check() == 0
    out = capsys.readouterr().out
    for name in TOOL_NAMES + PROMPT_NAMES:
        assert name in out


def test_main_self_check(capsys):
    assert main(["--self-check"]) == 0
    out = capsys.readouterr().out
    assert "search_evidence" in out
    assert "analyze_discussion" not in out


def test_search_decisions(settings, sample_record):
    text = tool_search_decisions(settings, "decorator")
    assert text.startswith(NOTICE)
    assert sample_record.id in text
    assert "decorator" in text.lower()


def test_search_decisions_rejects_unknown_status(settings):
    text = tool_search_decisions(settings, "decorator", status="bogus")
    assert text.startswith(NOTICE)
    assert "Unknown status 'bogus'" in text


def test_get_decision_card(settings, sample_record):
    text = tool_get_decision(settings, sample_record.id)
    assert text.startswith(NOTICE)
    assert sample_record.id in text
    assert "soft keyword" in text.lower()
    assert text == tool_get_decision(settings, sample_record.id, detail="card")


def test_get_decision_full_adds_the_quotes(settings, sample_record):
    card = tool_get_decision(settings, sample_record.id, detail="card")
    full = tool_get_decision(settings, sample_record.id, detail="full")
    assert full.startswith(NOTICE)
    assert sample_record.id in full
    assert "soft keyword" in full.lower()
    assert DECORATOR_QUOTE in full
    assert len(full) > len(card)


def test_get_decision_evidence_includes_the_reply_parent(settings, store, sample_record, synthetic_thread):
    """Only option A1 is kept: it cites posts 2 and 5, which both reply to post 1."""
    first = sample_record.options[0]
    narrowed = sample_record.model_copy(
        update={
            "options": [first],
            "outcome": "1 option: 1 rejected",
            "decided_by": first.decided_by,
            "decided_in_post": first.status_post,
        }
    )
    store.save_record(narrowed)
    opening, post5, post8 = synthetic_thread.posts[0], synthetic_thread.posts[4], synthetic_thread.posts[7]
    assert post5.reply_to == opening.id
    assert all(ev.post_id != opening.id for ev in first.evidence)

    text = tool_get_decision(settings, sample_record.id, detail="evidence")
    assert text.startswith(NOTICE)
    assert DECORATOR_QUOTE in text  # the cited sentence
    assert opening.sentences[0] in text  # the reply parent, which A1 never cites
    # Post 8 is not cited, is no reply parent, and does not follow a cited post.
    assert post8.sentences[0] not in text


def test_get_decision_evidence_without_the_thread_falls_back_to_the_full_card(settings, store, sample_record):
    orphan = sample_record.model_copy(update={"id": "dr-0000beef", "thread_id": "file:not-stored"})
    store.save_record(orphan)
    text = tool_get_decision(settings, orphan.id, detail="evidence")
    assert text.startswith(NOTICE)
    assert "The thread file:not-stored is not stored" in text
    assert DECORATOR_QUOTE in text  # the full card shows the quotes


def test_get_decision_unknown_detail(settings, sample_record):
    text = tool_get_decision(settings, sample_record.id, detail="Everything")
    assert text.startswith(NOTICE)
    assert "Unknown detail 'everything'" in text
    assert sample_record.id not in text


def test_get_decision_by_thread_id(settings, sample_record):
    assert sample_record.id in tool_get_decision(settings, "pep:9999")


def test_get_decision_unknown(settings):
    text = tool_get_decision(settings, "dr-00000000")
    assert text.startswith(NOTICE)
    assert "No decision record 'dr-00000000'" in text


def test_decisions_for_files(settings, sample_record):
    text = tool_decisions_for_files(settings, ["Lib/widgets.py"])
    assert text.startswith(NOTICE)
    assert sample_record.id in text
    # The thread names the file itself, so the link is direct.
    assert "Lib/widgets.py (mentioned, direct)" in text


def test_decisions_for_unlinked_files(settings):
    text = tool_decisions_for_files(settings, ["Doc/unrelated.rst"])
    assert "No recorded decisions are linked to Doc/unrelated.rst." in text


def test_check_change_with_paths(settings):
    text = tool_check_change(settings, paths=["Lib/lazy.py"])
    assert text.startswith(NOTICE)
    assert len(text) > len(NOTICE) + 2
    assert "lazy" in text.lower()
    assert "possible conflict" in text.lower()
    assert "invalid" not in text.lower()


def test_check_change_needs_input(settings):
    expected = {"ok": False, "error": "Give a PR URL, --paths, or --diff.", "fix": ""}
    assert json.loads(tool_check_change(settings)) == expected
    assert json.loads(tool_check_change(settings, description="only words")) == expected


def test_read_tools_answer_the_gate_error_on_an_empty_store(tmp_path):
    empty = Settings(db_path=str(tmp_path / "empty.db"))
    assert json.loads(tool_search_decisions(empty, "decorator"))["error"] == preflight.EMPTY_DB
    assert json.loads(tool_search_evidence(empty, ""))["error"] == preflight.EMPTY_QUERY


def test_ask_runs_a_discussion_and_answers_with_cards(settings, synthetic_thread, sample_record, monkeypatch):
    monkeypatch.setattr(mcp_server, "make_llm", lambda settings, store=None: ScriptedLLM({}))
    monkeypatch.setattr(mcp_server, "load_source", lambda ref, settings=None, client=None: synthetic_thread)
    monkeypatch.setattr(mcp_server, "compile_thread", lambda thread, llm, settings, progress=None: sample_record)
    text = tool_ask(settings, "pep:9999", "why not a decorator?")
    assert text.startswith(NOTICE)
    assert "Read 1 thread(s):" in text
    assert make_record_id("pep:9999") in text


def test_ask_gates_answer_json(settings, monkeypatch):
    monkeypatch.setattr(mcp_server, "make_llm", lambda settings, store=None: ScriptedLLM({}))
    assert json.loads(tool_ask(settings, "https://github.com/example/widgets")) == {
        "ok": False,
        "error": ASK_HELP,
        "fix": "",
    }
    assert json.loads(tool_ask(settings, "hello world", "why?"))["error"] == preflight.SOURCE_HELP


def test_search_evidence_returns_uncompiled_posts(settings):
    text = tool_search_evidence(settings, "decorator")
    assert text.startswith(NOTICE)
    assert "uncompiled" in text.lower()
    assert "decorator" in text.lower()


def test_search_evidence_no_match(settings):
    text = tool_search_evidence(settings, "qwertyzzz")
    assert text.startswith(NOTICE)
    assert 'No stored posts match "qwertyzzz".' in text


def test_budget_cap(settings, sample_record):
    full = tool_get_decision(settings, sample_record.id, detail="full")
    small = tool_get_decision(settings, sample_record.id, detail="full", budget_tokens=80)
    assert len(full) > 80 * 4
    assert len(small) <= 80 * 4
    assert small.startswith(NOTICE)
    assert "Cut to fit budget_tokens=80" in small
    assert len(tool_get_decision(settings, sample_record.id, detail="evidence", budget_tokens=80)) <= 80 * 4
    assert len(tool_search_decisions(settings, "decorator", budget_tokens=80)) <= 80 * 4
    assert len(tool_search_evidence(settings, "decorator", budget_tokens=80)) <= 80 * 4
    # Budgets above 10,000 tokens are clamped.
    assert len(tool_get_decision(settings, sample_record.id, detail="full", budget_tokens=10**9)) <= 10000 * 4


def test_tools_through_the_server(settings, sample_record):
    server = build_server(settings)
    text = flatten(asyncio.run(server.call_tool("get_decision", {"decision_id": sample_record.id})))
    assert sample_record.id in text
    arguments = {"decision_id": sample_record.id, "detail": "evidence"}
    text = flatten(asyncio.run(server.call_tool("get_decision", arguments)))
    assert DECORATOR_QUOTE in text
    text = flatten(asyncio.run(server.call_tool("search_evidence", {"query": "decorator", "limit": 3})))
    assert "uncompiled" in text.lower()


def test_review_prompt():
    text = review_prompt("Lib/widgets.py, Lib/lazy.py", "make widgets lazy by default")
    assert 'decisions_for_files tool with paths ["Lib/widgets.py", "Lib/lazy.py"]' in text
    assert "check_change" in text
    assert "search_evidence" in text  # the fallback when no record matches
    assert '"make widgets lazy by default"' in text
    assert "not instructions" in text
    assert "the files you plan to change" in review_prompt()


def test_tool_descriptions_route_decision_questions(settings):
    server = build_server(settings)
    tools = getattr(asyncio.run(server.list_tools()), "tools", None) or asyncio.run(server.list_tools())
    descriptions = {tool.name: tool.description or "" for tool in tools}
    assert set(descriptions) == set(TOOL_NAMES)
    for name, text in descriptions.items():
        assert "decided" in text or "rejected" in text, name
    assert descriptions["ask"].startswith("Call this first when the user asks why something was decided")
    assert "from memory" in descriptions["ask"]
    for name in TOOL_NAMES:
        if name != "ask":
            assert "Read-only" in descriptions[name], name
