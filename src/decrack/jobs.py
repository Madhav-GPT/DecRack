"""Background jobs: ingest a discussion and extract its decision record.

The MCP tool ``analyze_discussion`` has to answer at once, so the slow work
runs in a daemon thread and reports progress on a row in the ``jobs`` table.
Every job opens its own Store, because a SQLite connection must never be
shared between threads.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from decrack import sources
from decrack.config import Settings
from decrack.pipeline.llm import LLM, make_llm
from decrack.pipeline.roles import assign_roles
from decrack.pipeline.run import compile_thread
from decrack.store import Store

log = logging.getLogger(__name__)


def start_job(source: str, settings: Settings) -> str:
    """Queue a job for ``source``, start it in a daemon thread and return its id."""
    with Store(settings.db_path) as store:
        job = store.create_job(source)
    worker = threading.Thread(
        target=run_job,
        args=(job.id, source, settings),
        name=f"decrack-job-{job.id}",
        daemon=True,
    )
    worker.start()
    return job.id


def run_job(job_id: str, source: str, settings: Settings, llm: LLM | None = None) -> None:
    """Ingest and extract ``source``, recording progress on the job. Never raises.

    ``llm`` replaces the configured model (tests pass a ScriptedLLM).
    """
    try:
        store = Store(settings.db_path)
    except Exception:
        log.exception("job %s: cannot open the store at %s", job_id, settings.db_path)
        return
    try:
        store.update_job(job_id, status="running", progress=0.05, message=f"Loading {source}")
        thread = assign_roles(sources.load(source, settings))
        store.save_thread(thread)
        store.update_job(job_id, progress=0.2, message=f"Loaded {len(thread.posts)} posts from {thread.id}")

        model = llm if llm is not None else make_llm(settings, store)

        def report(message: str) -> None:
            store.update_job(job_id, message=message)

        record = compile_thread(thread, model, settings, progress=report)
        store.save_record(record)
        store.update_job(
            job_id,
            status="done",
            progress=1.0,
            message=f"Stored {record.id}: {record.outcome}",
            record_id=record.id,
            finished=True,
        )
    except Exception as exc:  # the thread is the last place this error can be seen
        message = f"{type(exc).__name__}: {exc}"
        log.warning("job %s failed: %s", job_id, message, exc_info=True)
        try:
            store.update_job(job_id, status="failed", message=message, finished=True)
        except Exception:
            log.exception("job %s: cannot record the failure", job_id)
    finally:
        store.close()


def job_status(job_id: str, settings: Settings) -> dict[str, Any] | None:
    """The job as a JSON-ready dict, or None when there is no such job."""
    with Store(settings.db_path) as store:
        job = store.get_job(job_id)
    return job.model_dump(mode="json") if job is not None else None
