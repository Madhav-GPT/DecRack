"""Invariants over the committed examples/ outputs.

Every example folder written by `decrack run --out` or `decrack eval` must pass the
same quote check CI runs (`decrack verify examples`): each evidence quote equals
its cited sentences and is a substring of its post, and every option has evidence.
With no examples committed yet, the test is skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from decrack.verify import verify_examples

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_committed_examples_pass_the_quote_check():
    checked, problems = verify_examples(EXAMPLES)
    if checked == 0:
        pytest.skip("no examples with thread.json + records.json yet")
    assert problems == []
