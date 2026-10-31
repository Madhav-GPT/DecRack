"""jobs: ingest + extract in a job, success and failure, with a scripted model."""

import json
import time

import pytest

from decrack.config import Settings
from decrack.jobs import job_status, run_job, start_job
from decrack.pipeline.llm import ScriptedLLM
from decrack.store import Store

# One sentence per post, so p1.s1, p2.s1 and p3.s1 certainly exist.
POSTS = [
    {"author": "alice", "text": "I propose a lazy keyword for imports."},
    {"author": "bob", "text": "Why not use a decorator instead of a keyword?"},
    {"author": "alice", "text": "We reject the decorator because it cannot apply to imports."},
]
THREAD_ID = "file:lazy-imports"


def map_response(messages: list[dict]) -> dict:
    return {
        "items": [
            {
                "alt_ref": "new",
                "alternative": "Lazy keyword for imports",
                "act": "propose",
                "evidence_type": "proposal",
                "reason": "",
                "cites": ["p1.s1"],
            },
            {
                "alt_ref": "new",
                "alternative": "Use a decorator",
                "act": "propose",
                "evidence_type": "proposal",
                "reason": "",
                "cites": ["p2.s1"],
            },
            {
                "alt_ref": "new",
                "alternative": "Use a decorator",
                "act": "reject",
                "evidence_type": "decision_statement",
                "reason": "It cannot apply to imports.",
                "cites": ["p3.s1"],
            },
        ]
    }


@pytest.fixture
def settings(tmp_path) -> Settings:
    # The optional model steps (merge, refine_reasons, support) are off, so "map" is the only step called.
    return Settings(
        db_path=str(tmp_path / "jobs.db"), merge_with_llm=False, refine_reasons=False, support_check=False
    )


@pytest.fixture
def source(tmp_path) -> str:
    path = tmp_path / "lazy-imports.json"
    path.write_text(json.dumps(POSTS), encoding="utf-8")
    return str(path)


def new_job(settings: Settings, source: str) -> str:
    with Store(settings.db_path) as store:
        return store.create_job(source).id


def test_run_job_done(settings, source):
    job_id = new_job(settings, source)
    llm = ScriptedLLM({"map": map_response})
    run_job(job_id, source, settings, llm=llm)

    job = job_status(job_id, settings)
    assert job["status"] == "done", job["message"]
    assert job["progress"] == 1.0
    assert job["record_id"]
    assert job["finished_at"] is not None
    assert llm.requests and all(step == "map" for step, _ in llm.requests)
    with Store(settings.db_path) as store:
        record = store.get_record(job["record_id"])
        thread = store.load_thread(THREAD_ID)
    assert record is not None
    assert record.thread_id == THREAD_ID
    assert thread is not None
    # Roles are assigned before the thread is stored: the files connector makes post 1's author the author.
    assert thread.posts[0].role == "author"
    assert all(post.role != "unknown" for post in thread.posts)


def test_run_job_reports_loader_error(settings, monkeypatch):
    def broken(ref, settings=None, client=None):
        raise ValueError(f"cannot read {ref}")

    monkeypatch.setattr("decrack.sources.load", broken)
    job_id = new_job(settings, "nowhere")
    run_job(job_id, "nowhere", settings, llm=ScriptedLLM({}))

    job = job_status(job_id, settings)
    assert job["status"] == "failed"
    assert job["message"] == "ValueError: cannot read nowhere"
    assert job["record_id"] is None
    assert job["finished_at"] is not None


def test_run_job_bad_source(settings, tmp_path):
    missing = str(tmp_path / "missing.json")
    job_id = new_job(settings, missing)
    run_job(job_id, missing, settings, llm=ScriptedLLM({}))

    job = job_status(job_id, settings)
    assert job["status"] == "failed"
    assert job["message"]
    assert job["record_id"] is None


def test_run_job_model_error_fails_the_job(settings, source):
    job_id = new_job(settings, source)
    run_job(job_id, source, settings, llm=ScriptedLLM({}))  # no scripted "map" response

    job = job_status(job_id, settings)
    assert job["status"] == "failed"
    assert job["message"].startswith("LLMError")


def test_start_job_runs_in_background(settings, source, monkeypatch):
    monkeypatch.setattr("decrack.jobs.make_llm", lambda settings, store=None: ScriptedLLM({"map": map_response}))
    job_id = start_job(source, settings)

    deadline = time.monotonic() + 30
    job = job_status(job_id, settings)
    while job["status"] not in ("done", "failed") and time.monotonic() < deadline:
        time.sleep(0.1)
        job = job_status(job_id, settings)
    assert job["status"] == "done", job["message"]
    assert job["record_id"]


def test_unknown_job(settings):
    assert job_status("no-such-job", settings) is None
