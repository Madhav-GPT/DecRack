"""Command-line interface: ``decrack <command>``.

Commands are thin. They build Settings from the global options, open the
Store, call the library and print. Results go to stdout and progress to
stderr. Expected failures (bad input, network, model, disk, database, git)
print one line on stderr and exit with code 1, without a traceback.
"""

import json
import re
import sqlite3
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, List, Optional

import httpx
import typer
from pydantic import BaseModel

from decrack import export_okf, search, surface, verify
from decrack.config import Settings, load_settings
from decrack.doctor import run_doctor
from decrack.models import DecisionRecord, Thread
from decrack.pipeline.llm import LLMError, make_llm
from decrack.pipeline.roles import assign_roles
from decrack.pipeline.run import compile_thread
from decrack.sources import load as load_source
from decrack.store import Store

app = typer.Typer(
    help="DecRack: recover decisions and rejected ideas from public discussions with a local open-weight model.",
    no_args_is_help=True,
)
export_app = typer.Typer(help="Write stored records or model calls out as files.", no_args_is_help=True)
app.add_typer(export_app, name="export")

EXPECTED_ERRORS = (
    ValueError,
    RuntimeError,  # e.g. the GitHub rate limit, or Discourse rate-limiting every retry
    LLMError,
    httpx.HTTPError,
    httpx.InvalidURL,
    OSError,
    sqlite3.Error,
    subprocess.SubprocessError,
)
PEP_REF = re.compile(r"^(?:pep[\s:_-]*)?0*(\d{1,5})$", re.IGNORECASE)


@contextmanager
def expected_errors() -> Iterator[None]:
    """Turn an expected failure into one line on stderr and exit code 1."""
    try:
        yield
    except EXPECTED_ERRORS as exc:
        typer.echo(f"error: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from None


def progress(message: str) -> None:
    """Progress goes to stderr so stdout holds only results."""
    typer.echo(message, err=True)


def settings_of(ctx: typer.Context) -> Settings:
    """The Settings built from the global options."""
    settings = ctx.find_object(Settings)
    return settings if settings is not None else load_settings()


def pep_number(ref: str) -> int | None:
    """``pep:830``, ``PEP 830``, ``pep-0830`` or ``830`` -> 830; anything else -> None."""
    match = PEP_REF.match(ref.strip())
    return int(match.group(1)) if match else None


def ingest_thread(store: Store, ref: str, settings: Settings) -> Thread:
    """Load a discussion, assign author/decider/maintainer roles and store it."""
    thread = assign_roles(load_source(ref, settings))
    store.save_thread(thread)
    return thread


def compile_and_save(store: Store, thread: Thread, settings: Settings) -> DecisionRecord:
    """Extract the thread's decision record with the configured model and store it."""
    llm = make_llm(settings, store)
    record = compile_thread(thread, llm, settings, progress=progress)
    store.save_record(record)
    return record


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_example(out: Path, thread: Thread, records: list[DecisionRecord]) -> list[Path]:
    """Write ``out/thread.json``, ``out/records.json`` (always a list) and ``out/run.json``; return the paths.

    ``run.json`` is the first record's ``run`` block: model, digest, Ollama version,
    parameters and source allowlist. ``decrack verify`` reads all three.
    """
    files: dict[str, Any] = {
        "thread.json": thread.model_dump(mode="json"),
        "records.json": [record.model_dump(mode="json") for record in records],
    }
    run = records[0].run if records else None
    if run is not None:
        files["run.json"] = run.model_dump(mode="json")
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        write_json(out / name, data)
    return [out / name for name in files]


def hit_block(record: DecisionRecord, why: str = "") -> str:
    """A record's compact card, which always shows its id, after a line saying why it matched."""
    card = search.render_card(record, detail="card")
    if record.id not in card:
        card += f"\nRecord id: `{record.id}`"
    return f"Matched: {why}\n\n{card}" if why else card


def to_jsonable(value: Any) -> Any:
    """``json.dumps`` fallback for models, sets and other objects in a check-pr result."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    return str(value)


@app.callback()
def global_options(
    ctx: typer.Context,
    db: Annotated[
        Optional[str], typer.Option("--db", help="SQLite file (default: decrack.toml, $DECRACK_DB or decrack.db).")
    ] = None,
    model: Annotated[Optional[str], typer.Option("--model", help="Ollama model tag (default: qwen3.5:4b).")] = None,
    ollama_host: Annotated[
        Optional[str], typer.Option("--ollama-host", help="Ollama server address (default: http://127.0.0.1:11434).")
    ] = None,
) -> None:
    # Every command, including the export subcommands, finds these settings on the context.
    ctx.obj = load_settings(db=db, model=model, ollama_host=ollama_host)


@app.command("ingest")
def ingest_cmd(
    ctx: typer.Context,
    ref: Annotated[
        str,
        typer.Argument(
            help="pep:N, a discuss.python.org topic URL, a GitHub issue or PR (URL or owner/repo#n), "
            "or a local .json/.jsonl/.md/.txt file."
        ),
    ],
) -> None:
    """Fetch a discussion and store its posts (no model needed)."""
    settings = settings_of(ctx)
    with expected_errors(), Store(settings.db_path) as store:
        thread = ingest_thread(store, ref, settings)
    typer.echo(f"Stored {thread.id}: {len(thread.posts)} posts — {thread.title}")


@app.command("extract")
def extract_cmd(
    ctx: typer.Context,
    thread_id: Annotated[str, typer.Argument(help="Id printed by ingest, such as pep:830 or file:notes.")],
) -> None:
    """Extract the decision record of a stored thread with the local model."""
    settings = settings_of(ctx)
    with expected_errors(), Store(settings.db_path) as store:
        thread = store.load_thread(thread_id)
        if thread is None:
            typer.echo(f"error: no stored thread {thread_id!r}; run `decrack ingest` first.", err=True)
            raise typer.Exit(1)
        record = compile_and_save(store, thread, settings)
    typer.echo(search.render_card(record))


@app.command("run")
def run_cmd(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="Anything ingest accepts.")],
    out: Annotated[
        Optional[Path],
        typer.Option("--out", help="Also write DIR/thread.json, DIR/records.json and DIR/run.json."),
    ] = None,
) -> None:
    """Ingest and extract in one step."""
    settings = settings_of(ctx)
    written: list[Path] = []
    with expected_errors(), Store(settings.db_path) as store:
        thread = ingest_thread(store, ref, settings)
        progress(f"Stored {thread.id}: {len(thread.posts)} posts — {thread.title}")
        record = compile_and_save(store, thread, settings)
        if out is not None:
            written = write_example(out, thread, [record])
    typer.echo(search.render_card(record))
    if written:
        typer.echo("Wrote " + ", ".join(str(path) for path in written))


@app.command("why")
def why_cmd(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Words, a question or a file path.")],
    limit: Annotated[int, typer.Option("--limit", min=1, help="Most records to show.")] = 5,
) -> None:
    """Search decision records; print their compact cards."""
    settings = settings_of(ctx)
    with expected_errors(), Store(settings.db_path) as store:
        hits = search.why(store, query, limit=limit)
    if not hits:
        typer.echo(f'No recorded decisions match "{query}".')
        return
    typer.echo(search.NOTICE)
    typer.echo("")
    typer.echo(search.pack([hit_block(hit.record, hit.why) for hit in hits], settings.budget_tokens))


@app.command("search-evidence")
def search_evidence_cmd(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Words to look for in the stored posts.")],
    limit: Annotated[int, typer.Option("--limit", min=1, help="Most posts to show.")] = 10,
) -> None:
    """Search the raw stored posts (uncompiled, unchecked): the fallback when `why` finds no record."""
    settings = settings_of(ctx)
    with expected_errors(), Store(settings.db_path) as store:
        rows = store.search_posts(query, limit)
    if not rows:
        typer.echo(f'No stored posts match "{query}".')
        return
    typer.echo(search.NOTICE)
    typer.echo("")
    typer.echo(search.pack([search.render_posts(rows)], settings.budget_tokens))


@app.command("check-pr")
def check_pr_cmd(
    ctx: typer.Context,
    pr_url: Annotated[Optional[str], typer.Argument(help="GitHub PR URL or owner/repo#n.")] = None,
    paths: Annotated[
        Optional[List[str]],
        typer.Option("--paths", help="Changed file paths; repeat the option or separate paths with commas."),
    ] = None,
    diff: Annotated[Optional[str], typer.Option("--diff", help="Commit range BASE..HEAD in the --repo clone.")] = None,
    repo: Annotated[
        Optional[Path], typer.Option("--repo", help="Local git clone for --diff (default: current directory).")
    ] = None,
    description: Annotated[Optional[str], typer.Option("--description", help="What the change does.")] = None,
    fmt: Annotated[str, typer.Option("--format", help="md or json.")] = "md",
) -> None:
    """Show related history and possible conflicts: recorded decisions and rejected options for a change.

    It reports history to weigh, never a verdict, and never posts anything.
    """
    settings = settings_of(ctx)
    if fmt not in ("md", "json"):
        raise typer.BadParameter("use md or json", param_hint="--format")
    if diff and ".." not in diff:
        raise typer.BadParameter("expected BASE..HEAD", param_hint="--diff")
    path_list = [part.strip() for value in paths or [] for part in value.split(",") if part.strip()]
    if not (pr_url or path_list or diff or description):
        typer.echo("error: give a PR URL, --paths, --diff BASE..HEAD or --description.", err=True)
        raise typer.Exit(2)
    repo_dir = str(repo) if repo is not None else (str(Path.cwd()) if diff else None)
    with expected_errors(), Store(settings.db_path) as store:
        result = surface.check_change(
            store,
            pr_url=pr_url,
            paths=path_list or None,
            description=description,
            diff=diff,
            repo_dir=repo_dir,
            budget_tokens=settings.budget_tokens,
        )
    if fmt == "json":
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False, default=to_jsonable))
    else:
        typer.echo(result["markdown"])


@export_app.command("okf")
def export_okf_cmd(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="Folder for the bundle (index.md, decisions/, log.md).")],
) -> None:
    """Write every stored record as an OKF+MADR markdown bundle."""
    settings = settings_of(ctx)
    with expected_errors(), Store(settings.db_path) as store:
        records = store.all_records()
        threads: dict[str, Thread] = {}
        for record in records:
            thread = store.load_thread(record.thread_id)
            if thread is not None:
                threads[record.thread_id] = thread
        files = export_okf.export_bundle(records, out, threads=threads)
    typer.echo(f"Exported {len(records)} decision records to {out} ({len(files)} files)")


@export_app.command("calls")
def export_calls_cmd(
    ctx: typer.Context,
    out: Annotated[
        Optional[Path],
        typer.Option("--out", help="JSONL file (default: the replay_file setting, tests/fixtures/llm_calls.jsonl)."),
    ] = None,
) -> None:
    """Export the recorded model calls as JSONL, the input of replay mode."""
    settings = settings_of(ctx)
    target = out if out is not None else Path(settings.replay_file)
    with expected_errors(), Store(settings.db_path) as store:
        target.parent.mkdir(parents=True, exist_ok=True)
        count = store.export_llm_calls(target)
    typer.echo(f"Exported {count} model calls to {target}")


@app.command("eval")
def eval_cmd(
    ctx: typer.Context,
    refs: Annotated[List[str], typer.Argument(help="PEPs to evaluate: pep:830, 'PEP 830' or 830.")],
    gold: Annotated[Path, typer.Option("--gold", help="Folder of gold files (pep-NNNN.json).")] = Path("eval/gold"),
    out: Annotated[
        Path, typer.Option("--out", help="Folder for pep-NNNN/ run folders and eval-summary.md.")
    ] = Path("examples/runs"),
    closed_book: Annotated[
        bool, typer.Option("--closed-book", help="Also ask the model from memory alone, as a baseline.")
    ] = False,
    judge: Annotated[bool, typer.Option("--judge", help="Let the model judge near matches against gold.")] = False,
) -> None:
    """Run the withheld-PEP evaluation and print its summary."""
    settings = settings_of(ctx)
    peps: list[int] = []
    for ref in refs:
        number = pep_number(ref)
        if number is None:
            typer.echo(f"error: {ref!r} is not a PEP reference; use pep:830, 'PEP 830' or 830.", err=True)
            raise typer.Exit(1)
        peps.append(number)

    # Imported here so every other command works without the evaluation module.
    from decrack import evaluate

    # The evaluation must never read the PEP text it scores against, so the leak guard is always on.
    settings = settings.model_copy(update={"eval_mode": True})
    with expected_errors(), Store(settings.db_path) as store:
        evaluate.run_eval(
            peps,
            gold,
            out,
            settings,
            make_llm(settings, store),
            store,
            closed_book_baseline=closed_book,
            judge=judge,
            progress=progress,
        )
    summary = out / "eval-summary.md"
    typer.echo(f"Wrote {summary}")
    if summary.is_file():
        typer.echo(summary.read_text(encoding="utf-8"))


@app.command("verify")
def verify_cmd(
    directory: Annotated[
        Path,
        typer.Argument(
            exists=True, file_okay=False, help="Folder searched for thread.json + records.json pairs, recursively."
        ),
    ],
) -> None:
    """Re-check every quote in exported records against its thread; exit 1 on any problem."""
    raise typer.Exit(verify.main(directory))


@app.command("doctor")
def doctor_cmd(ctx: typer.Context) -> None:
    """Check Ollama, the model and OpenCode; print the OpenCode MCP snippet."""
    lines, code = run_doctor(settings_of(ctx))
    for line in lines:
        typer.echo(line)
    raise typer.Exit(code)


@app.command("mcp")
def mcp_cmd(ctx: typer.Context) -> None:
    """Serve DecRack's tools over MCP stdio (for OpenCode or any MCP client)."""
    # Imported here: only this command needs the mcp package.
    from decrack import mcp_server

    mcp_server.serve(settings_of(ctx))


def main() -> None:
    """Entry point of the ``decrack`` script."""
    app()


if __name__ == "__main__":
    main()
