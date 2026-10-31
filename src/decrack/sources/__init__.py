"""Acquire: turn a reference into a Thread (no model involved).

``load(ref)`` accepts ``pep:830``, a discuss.python.org (or other Discourse)
topic URL, a GitHub issue or pull request URL or ``owner/repo#n``, or a local
file. An existing local file wins over the GitHub short form, so a path such
as ``notes/chat#3`` is read as a file when it exists. Every connector returns
the same Thread/Post contract, with stable post ids, NFC text, sentence spans
and hashes; this module only picks the connector. Roles are assigned later,
in the compile stage.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from decrack import __version__
from decrack.config import Settings
from decrack.models import Thread
from decrack.sources import discourse, files, github, peps
from decrack.text import finalize_thread

PEP_REF_RE = re.compile(r"^\s*pep[:\s_-]*(\d+)\s*$", re.IGNORECASE)
DISCOURSE_URL_RE = re.compile(r"^https?://[^/\s]+/t/\S+", re.IGNORECASE)
FILE_SUFFIXES = {".json", ".jsonl", ".md", ".markdown", ".txt"}
# DecRack reads discussions only; fetching the PEP text would leak the answer key.
FORBIDDEN_MARKERS = ("peps.python.org/pep-", "github.com/python/peps", "raw.githubusercontent.com/python/peps")
ACCEPTED_FORMS = (
    "pep:N, a discuss.python.org topic URL, a GitHub issue or pull request URL (or owner/repo#n), "
    "or a .json/.jsonl/.md/.txt file"
)


def make_client() -> httpx.Client:
    """The HTTP client used for every connector."""
    return httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": f"decrack/{__version__}"})


def _is_file(path: Path) -> bool:
    """``path.is_file()``, but False for a string that cannot name a file at all (such as a too-long URL)."""
    try:
        return path.is_file()
    except OSError:
        return False


def detect(ref: str) -> str:
    """Which connector handles ``ref``: "pep", "file", "github" or "discourse"."""
    value = ref.strip()
    lowered = value.lower()
    if any(marker in lowered for marker in FORBIDDEN_MARKERS):
        raise ValueError("DecRack reads discussions, not PEP text. Use pep:N to load a PEP's discussion threads.")
    if PEP_REF_RE.match(value):
        return "pep"
    path = Path(value).expanduser()
    # Before the GitHub check: an existing "notes/chat#3" is a file, not owner/repo#n.
    if _is_file(path):
        return "file"
    if github.is_github_ref(value):
        return "github"
    if DISCOURSE_URL_RE.match(value):
        return "discourse"
    if not lowered.startswith(("http://", "https://")) and (
        path.suffix.lower() in FILE_SUFFIXES or "/" in value or "\\" in value
    ):
        raise FileNotFoundError(f"No such file: {value}")
    raise ValueError(f"Unrecognized source {value!r}. Use {ACCEPTED_FORMS}.")


def load(ref: str, settings: Settings | None = None, client: httpx.Client | None = None) -> Thread:
    """Fetch or read ``ref`` and return its Thread with NFC text, sentences, spans and hashes filled in.

    With ``settings.eval_mode`` on, the PEP leak guard blanks posts that paste the PEP.
    """
    settings = settings or Settings()
    value = ref.strip()
    kind = detect(value)
    if kind == "file":
        return finalize_thread(files.load_file(Path(value).expanduser()))

    http = client if client is not None else make_client()
    try:
        if kind == "pep":
            number = int(PEP_REF_RE.match(value).group(1))
            thread = peps.load_pep(number, http, leak_guard=settings.eval_mode)
        elif kind == "github":
            thread = github.load_github(value, http)
        else:
            thread = discourse.load_topic(value, http)
    finally:
        if client is None:
            http.close()
    return finalize_thread(thread)
