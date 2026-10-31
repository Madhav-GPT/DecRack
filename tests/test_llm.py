"""The Ollama client, replay, scripted answers, runtime info and cache keys, all offline."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from decrack.config import DEFAULT_MODEL, DEFAULT_OLLAMA_HOST, Settings
from decrack.models import ACTS, MapOutput
from decrack.pipeline.llm import (
    NUM_PREDICT,
    LLMError,
    LLMOutputError,
    LLMUnavailableError,
    OllamaLLM,
    ReplayLLM,
    ReplayMissError,
    ScriptedLLM,
    build_request,
    call_key,
    inline_schema,
    loose_key,
    make_llm,
)
from decrack.pipeline.support import SupportOutput

MESSAGES = [{"role": "system", "content": "Label the posts."}, {"role": "user", "content": "Posts go here."}]
GOOD = {
    "items": [
        {
            "alt_ref": "new",
            "alternative": "Soft keyword",
            "act": "propose",
            "reason": "",
            "cites": ["p7.s1"],
        }
    ]
}
OTHER = {"items": []}
OPTIONS = {"num_ctx": 32768, "temperature": 0, "num_predict": NUM_PREDICT}
EXTRA = {
    "digest": "sha256:" + "a" * 64,
    "prompt_version": "decrack-prompts-2",
    "schema_version": "decrack-record/0.2",
    "window": [["dpo:99999:1007", 1, "b" * 64, 1, 2]],
    "known": [["A1", "Hard lazy keyword", "A new reserved keyword lazy."]],
    "chain": "",
}


class FakeStore:
    """The two Store methods OllamaLLM uses, backed by a dict."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get_llm_call(self, key: str) -> dict | None:
        row = self.rows.get(key)
        return None if row is None else row["response"]

    def put_llm_call(self, key, step, model, request, response, ms=0, tokens_in=0, tokens_out=0) -> None:
        self.rows[key] = {
            "step": step,
            "model": model,
            "request": request,
            "response": response,
            "ms": ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }


def reply(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "qwen2.5:1.5b",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "prompt_eval_count": 120,
            "eval_count": 30,
        },
    )


def mock_client(*responses: httpx.Response) -> tuple[httpx.Client, list[tuple[str, dict]]]:
    """A client that answers POSTs with ``responses`` in order and records (url, body) of each request."""
    sent: list[tuple[str, dict]] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((str(request.url), json.loads(request.content)))
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler)), sent


def map_request(model: str = DEFAULT_MODEL, options: dict = OPTIONS, extra: dict | None = None) -> dict:
    return build_request(model, "map", MESSAGES, MapOutput, options, False, extra)


# OllamaLLM


def test_ollama_request_shape_and_think_stripping():
    client, sent = mock_client(reply("<think>Let me look at the posts.</think>\n" + json.dumps(GOOD)))
    llm = OllamaLLM(model="qwen2.5:1.5b", num_ctx=8192, client=client)
    assert llm.complete_json("map", MESSAGES, MapOutput, key_extra=EXTRA) == GOOD
    assert (llm.calls, llm.cache_hits, llm.tokens_in, llm.tokens_out) == (1, 0, 120, 30)

    [(url, body)] = sent
    assert url == f"{DEFAULT_OLLAMA_HOST}/api/chat"
    assert set(body) == {"model", "messages", "format", "stream", "options"}  # key_extra stays local
    assert body["model"] == "qwen2.5:1.5b"
    assert body["messages"] == MESSAGES
    assert body["stream"] is False
    assert "think" not in body  # sent only when think=True
    assert body["options"] == {"num_ctx": 8192, "temperature": 0, "num_predict": NUM_PREDICT}
    # Grammar bounds: a looping small model must close the items array and its names.
    assert body["format"]["properties"]["items"]["maxItems"] == 20
    assert isinstance(body["format"], dict)
    assert "$ref" not in json.dumps(body["format"])
    assert "$defs" not in body["format"]
    item = body["format"]["properties"]["items"]["items"]["properties"]
    assert item["act"]["enum"] == list(ACTS)
    assert "evidence_type" not in item  # code derives it; the model is not asked


def test_ollama_retries_once_with_the_error():
    client, sent = mock_client(
        reply("I think the answer is a soft keyword."),
        reply("```json\n" + json.dumps(GOOD) + "\n```"),
    )
    llm = OllamaLLM(client=client)
    assert llm.complete_json("map", MESSAGES, MapOutput) == GOOD
    assert len(sent) == 2
    retry = sent[1][1]["messages"]
    assert retry[:2] == MESSAGES
    assert retry[2] == {"role": "assistant", "content": "I think the answer is a soft keyword."}
    assert retry[3]["role"] == "user"
    assert "not valid" in retry[3]["content"]
    assert (llm.tokens_in, llm.tokens_out) == (240, 60)  # both attempts count


def cut_off(content: str) -> httpx.Response:
    """An Ollama answer that stopped at the num_predict cap."""
    body = {"message": {"role": "assistant", "content": content}, "done": True, "done_reason": "length"}
    return httpx.Response(200, json={**body, "prompt_eval_count": 120, "eval_count": NUM_PREDICT})


def test_a_cut_off_answer_is_retried_without_echoing_it():
    looping = '{"items": [' + '{"alt_ref": "new", "alternative": "x", ' * 50
    client, sent = mock_client(cut_off(looping), reply(json.dumps(GOOD)))
    llm = OllamaLLM(client=client)
    assert llm.complete_json("map", MESSAGES, MapOutput) == GOOD
    retry = sent[1][1]["messages"]
    assert retry[:2] == MESSAGES
    assert len(retry) == 3  # no assistant turn: the cut-off loop is not sent back
    assert retry[2]["role"] == "user" and "cut off" in retry[2]["content"]


def test_two_cut_off_answers_skip_the_call():
    client, sent = mock_client(cut_off("{"), cut_off("{"))
    with pytest.raises(LLMOutputError, match="cut off"):
        OllamaLLM(client=client).complete_json("map", MESSAGES, MapOutput)
    assert len(sent) == 2


def test_a_read_timeout_costs_one_call_but_a_connect_timeout_stops_the_run():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    with pytest.raises(LLMOutputError):
        OllamaLLM(client=httpx.Client(transport=httpx.MockTransport(slow))).complete_json("map", MESSAGES, MapOutput)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route", request=request)

    with pytest.raises(LLMUnavailableError):
        llm = OllamaLLM(client=httpx.Client(transport=httpx.MockTransport(unreachable)))
        llm.complete_json("map", MESSAGES, MapOutput)


def test_ollama_gives_up_after_one_retry():
    client, sent = mock_client(reply('{"items": "nope"}'), reply('{"items": [{"act": "maybe"}]}'))
    llm = OllamaLLM(client=client)
    with pytest.raises(LLMOutputError):
        llm.complete_json("map", MESSAGES, MapOutput)
    assert len(sent) == 2
    assert (llm.calls, llm.tokens_in, llm.tokens_out) == (1, 240, 60)


def test_a_repeated_call_is_served_from_the_store():
    store = FakeStore()
    client, sent = mock_client(reply(json.dumps(GOOD)), reply(json.dumps(OTHER)))
    llm = OllamaLLM(store=store, client=client)
    first = llm.complete_json("map", MESSAGES, MapOutput, key_extra=EXTRA)
    second = llm.complete_json("map", MESSAGES, MapOutput, key_extra=EXTRA)
    assert first == second == GOOD
    assert len(sent) == 1  # no second HTTP request
    assert (llm.calls, llm.cache_hits, llm.tokens_in, llm.tokens_out) == (2, 1, 120, 30)

    key = call_key(map_request(extra=EXTRA))
    assert list(store.rows) == [key]
    row = store.rows[key]
    assert (row["step"], row["model"], row["response"]) == ("map", DEFAULT_MODEL, GOOD)
    assert (row["tokens_in"], row["tokens_out"]) == (120, 30)
    assert row["request"]["schema"] == inline_schema(MapOutput.model_json_schema())
    assert row["request"]["extra"] == EXTRA

    # Another key_extra (here the chain of an edited earlier window) is another request.
    changed = {**EXTRA, "chain": "c" * 64}
    assert llm.complete_json("map", MESSAGES, MapOutput, key_extra=changed) == OTHER
    assert len(sent) == 2
    assert list(store.rows) == [key, call_key(map_request(extra=changed))]
    assert (llm.calls, llm.cache_hits) == (3, 1)


def test_think_is_sent_only_when_asked_for():
    client, sent = mock_client(reply(json.dumps(GOOD)), reply(json.dumps(OTHER)))
    llm = OllamaLLM(model="tiny", client=client)
    assert llm.complete_json("map", MESSAGES, MapOutput) == GOOD
    assert llm.complete_json("map", MESSAGES, MapOutput, think=True) == OTHER
    assert "think" not in sent[0][1]
    assert sent[1][1]["think"] is True
    assert '"think": true' in json.dumps(sent[1][1])


def test_the_think_flag_is_dropped_when_ollama_refuses_it():
    client, sent = mock_client(
        httpx.Response(400, json={"error": '"tiny" does not support thinking'}),
        reply(json.dumps(GOOD)),
    )
    llm = OllamaLLM(model="tiny", client=client)
    assert llm.complete_json("map", MESSAGES, MapOutput, think=True) == GOOD
    assert len(sent) == 2
    assert sent[0][1]["think"] is True
    assert "think" not in sent[1][1]


def test_a_connection_error_says_how_to_start_ollama():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    llm = OllamaLLM(model="qwen2.5:1.5b", client=httpx.Client(transport=httpx.MockTransport(refuse)))
    with pytest.raises(LLMUnavailableError) as info:
        llm.complete_json("map", MESSAGES, MapOutput)
    assert "ollama serve" in str(info.value)
    assert "ollama pull qwen2.5:1.5b" in str(info.value)


def test_a_missing_model_suggests_ollama_pull():
    client, _ = mock_client(httpx.Response(404, json={"error": "model 'qwen2.5:1.5b' not found"}))
    llm = OllamaLLM(model="qwen2.5:1.5b", client=client)
    with pytest.raises(LLMUnavailableError, match="ollama pull qwen2.5:1.5b"):
        llm.complete_json("map", MESSAGES, MapOutput)


# Runtime info


TAGS = {
    "models": [
        {"name": "test-model:b", "model": "test-model:b", "digest": "1" * 64},
        {"name": "qwen2.5:1.5b", "model": "qwen2.5:1.5b", "digest": "2" * 64},
        {"model": "local-notes:latest", "digest": "3" * 64},
    ]
}


def info_client(tags: httpx.Response, version: httpx.Response) -> tuple[httpx.Client, list[tuple[str, str]]]:
    """A client that answers ``GET /api/tags`` and ``GET /api/version``; records (method, path)."""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return tags if request.url.path == "/api/tags" else version

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_runtime_info_reads_the_model_digest_and_the_ollama_version():
    client, seen = info_client(httpx.Response(200, json=TAGS), httpx.Response(200, json={"version": "0.12.6"}))
    llm = OllamaLLM(model="qwen2.5:1.5b", client=client)
    assert llm.runtime_info() == {"model_digest": "2" * 64, "ollama_version": "0.12.6"}
    assert seen == [("GET", "/api/tags"), ("GET", "/api/version")]
    assert llm.calls == 0  # not a model call

    # The "model" field matches too, and a name without a tag means <name>:latest.
    client, _ = info_client(httpx.Response(200, json=TAGS), httpx.Response(200, json={"version": "0.12.6"}))
    assert OllamaLLM(model="local-notes", client=client).runtime_info()["model_digest"] == "3" * 64


def test_runtime_info_gives_empty_strings_when_anything_fails():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    offline = OllamaLLM(client=httpx.Client(transport=httpx.MockTransport(refuse)))
    assert offline.runtime_info() == {"model_digest": "", "ollama_version": ""}

    client, _ = info_client(httpx.Response(500, text="boom"), httpx.Response(200, text="not json"))
    assert OllamaLLM(client=client).runtime_info() == {"model_digest": "", "ollama_version": ""}

    # The model is not installed, and the version answer has no version.
    client, _ = info_client(httpx.Response(200, json=TAGS), httpx.Response(200, json={"other": 1}))
    assert OllamaLLM(model="test-model:c", client=client).runtime_info() == {"model_digest": "", "ollama_version": ""}

    # Half an answer is still used.
    missing = httpx.Response(404, text="404 page not found")
    client, _ = info_client(missing, httpx.Response(200, json={"version": "0.9"}))
    assert OllamaLLM(client=client).runtime_info() == {"model_digest": "", "ollama_version": "0.9"}


# ReplayLLM


def recorded(response: dict, model: str = "qwen2.5:1.5b", num_ctx: int = 32768, extra: dict | None = None) -> dict:
    """One JSONL row as ``Store.export_llm_calls`` writes it."""
    request = map_request(model, {"num_ctx": num_ctx, "temperature": 0, "num_predict": NUM_PREDICT}, extra)
    return {"key": call_key(request), "step": "map", "model": model, "request": request, "response": response}


def write_calls(path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_replay_strict_and_loose_hits(tmp_path):
    path = tmp_path / "calls.jsonl"
    chained = {**EXTRA, "chain": "c" * 64}
    write_calls(path, [recorded(GOOD, extra=EXTRA), recorded(OTHER, num_ctx=4096, extra=chained)])

    strict = ReplayLLM(path, model="qwen2.5:1.5b", num_ctx=32768)
    assert strict.complete_json("map", MESSAGES, MapOutput, key_extra=EXTRA) == GOOD
    assert (strict.mode, strict.calls, strict.cache_hits, strict.tokens_in, strict.tokens_out) == (
        "replay",
        1,
        1,
        0,
        0,
    )

    # Another model tag, num_ctx and digest (none, offline) still replay through the loose key ...
    loose = ReplayLLM(path, model="test-model:b", num_ctx=8192)
    assert loose.complete_json("map", MESSAGES, MapOutput, key_extra={**EXTRA, "digest": ""}) == GOOD
    assert loose.complete_json("map", MESSAGES, MapOutput, key_extra={**chained, "digest": ""}) == OTHER
    # ... but another chain, window or known state does not.
    for changed in ({"chain": "d" * 64}, {"window": []}, {"known": []}):
        with pytest.raises(ReplayMissError):
            loose.complete_json("map", MESSAGES, MapOutput, key_extra={**EXTRA, **changed})
    assert (loose.calls, loose.cache_hits) == (5, 2)


def test_a_replay_miss_names_the_step_key_and_how_to_record(tmp_path):
    path = tmp_path / "calls.jsonl"
    write_calls(path, [recorded(GOOD)])
    llm = ReplayLLM(path)
    different = [MESSAGES[0], {"role": "user", "content": "Different posts."}]
    with pytest.raises(ReplayMissError) as info:
        llm.complete_json("map", different, MapOutput)
    text = str(info.value)
    assert "'map'" in text
    assert call_key(build_request(DEFAULT_MODEL, "map", different, MapOutput, OPTIONS, False)) in text
    assert "decrack export calls --out" in text
    assert isinstance(info.value, LLMError)


def test_replay_without_a_file(tmp_path):
    llm = ReplayLLM(tmp_path / "missing-calls.jsonl")
    for _ in range(2):
        with pytest.raises(ReplayMissError, match="missing-calls.jsonl"):
            llm.complete_json("map", MESSAGES, MapOutput)


# Keys and schemas


def test_call_key_is_canonical():
    request = {
        "model": "m",
        "step": "map",
        "messages": MESSAGES,
        "schema": {"type": "object"},
        "options": {"num_ctx": 1, "temperature": 0},
        "think": False,
    }
    reordered = dict(reversed(list(request.items())))
    assert call_key(request) == call_key(reordered)
    assert call_key(request) == hashlib.sha256(
        json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert len(call_key(request)) == 64
    assert call_key(request) != call_key({**request, "think": True})
    assert call_key(request) != call_key({**request, "options": {"num_ctx": 2, "temperature": 0}})


def test_key_extra_goes_into_the_request_and_changes_the_key():
    plain = map_request()
    assert "extra" not in plain
    with_extra = map_request(extra=EXTRA)
    assert with_extra["extra"] == EXTRA
    assert {name: value for name, value in with_extra.items() if name != "extra"} == plain
    keys = {
        call_key(plain),
        call_key(with_extra),
        call_key(map_request(extra={**EXTRA, "chain": "c" * 64})),
        call_key(map_request(extra={**EXTRA, "digest": "sha256:" + "d" * 64})),
    }
    assert len(keys) == 4


def test_the_loose_key_ignores_model_options_and_digest():
    base = map_request("qwen2.5:1.5b", OPTIONS, EXTRA)
    other = map_request("test-model:b", {"num_ctx": 4096, "temperature": 0}, {**EXTRA, "digest": ""})
    assert call_key(base) != call_key(other)
    assert loose_key(base) == loose_key(other)
    # The rest of extra still counts.
    assert loose_key(base) != loose_key(map_request(extra={**EXTRA, "chain": "c" * 64}))
    assert loose_key(base) != loose_key(map_request(extra=None))
    # Without extra the loose key covers step, messages, schema and think only.
    assert loose_key(map_request()) == call_key(
        {"step": "map", "messages": MESSAGES, "schema": inline_schema(MapOutput.model_json_schema()), "think": False}
    )


def test_build_request_inlines_the_schema():
    request = build_request("m", "map", MESSAGES, MapOutput, OPTIONS, False)
    assert set(request) == {"model", "step", "messages", "schema", "options", "think"}
    assert request["schema"] == inline_schema(MapOutput.model_json_schema())
    assert build_request("m", "map", MESSAGES, request["schema"], OPTIONS, False) == request


def test_inline_schema_resolves_nested_refs():
    schema = {
        "$defs": {
            "Inner": {"type": "string"},
            "Outer": {"type": "object", "properties": {"inner": {"$ref": "#/$defs/Inner"}}},
        },
        "type": "object",
        "properties": {
            "outer": {"$ref": "#/$defs/Outer", "description": "kept"},
            "many": {"type": "array", "items": {"$ref": "#/$defs/Inner"}},
        },
    }
    assert inline_schema(schema) == {
        "type": "object",
        "properties": {
            "outer": {"type": "object", "properties": {"inner": {"type": "string"}}, "description": "kept"},
            "many": {"type": "array", "items": {"type": "string"}},
        },
    }
    assert "$defs" in schema  # the input is not changed
    flat = inline_schema(MapOutput.model_json_schema())
    assert "$ref" not in json.dumps(flat)
    assert "$defs" not in flat


# make_llm and ScriptedLLM


def test_every_llm_reports_its_mode_and_usage(tmp_path):
    client, _ = mock_client()
    for llm, mode in (
        (OllamaLLM(client=client), "live"),
        (ReplayLLM(tmp_path / "calls.jsonl"), "replay"),
        (ScriptedLLM(), "scripted"),
    ):
        assert llm.mode == mode
        assert (llm.calls, llm.cache_hits, llm.tokens_in, llm.tokens_out) == (0, 0, 0, 0)


def test_make_llm_picks_the_runtime(tmp_path):
    replay = make_llm(Settings(llm_mode="replay", replay_file=str(tmp_path / "calls.jsonl"), model="test-model:b"))
    assert isinstance(replay, ReplayLLM)
    assert (replay.model, replay.mode) == ("test-model:b", "replay")

    live = make_llm(Settings(model="test-model:b", num_ctx=16384))
    try:
        assert isinstance(live, OllamaLLM)
        assert (live.model, live.num_ctx, live.host, live.mode) == ("test-model:b", 16384, DEFAULT_OLLAMA_HOST, "live")
    finally:
        live.close()


def test_scripted_llm_queues_callables_and_errors():
    llm = ScriptedLLM({"map": [GOOD], "support": lambda messages: {"results": []}})
    assert llm.complete_json("map", MESSAGES, MapOutput, key_extra=EXTRA) == GOOD
    with pytest.raises(LLMError) as info:
        llm.complete_json("map", MESSAGES, MapOutput)
    assert not isinstance(info.value, LLMOutputError)

    # A callable answers every call for its step.
    assert llm.complete_json("support", MESSAGES, SupportOutput) == {"results": []}
    assert llm.complete_json("support", MESSAGES, SupportOutput) == {"results": []}

    llm.add("map", {"items": "bad"})
    with pytest.raises(LLMOutputError):
        llm.complete_json("map", MESSAGES, MapOutput)
    assert [step for step, _ in llm.requests] == ["map", "map", "support", "support", "map"]
    assert llm.key_extras == [EXTRA, None, None, None, None]
    assert llm.calls == 5
