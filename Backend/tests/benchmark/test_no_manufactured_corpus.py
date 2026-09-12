"""No annotated corpus may be committed to this repository.

A file of plausible-looking labels is indistinguishable from clinician-produced
data a few months from now, and every number computed from it would inherit
that. The distinction between "measured" and "made up" is the entire value of
the benchmark, and it survives only if it is impossible to blur by accident.

So the rule is structural: `benchmark/` holds documentation and nothing else,
the tests build their fixtures in memory, and this file fails if anything that
looks like a corpus appears in the tree.

The second half checks the consequence. With no corpus, every detector must
still say it has never been measured - and that is what the framework reports
today.
"""
from __future__ import annotations

import json
from pathlib import Path

from intelligence.benchmark import readiness
from intelligence.benchmark.promotion import (
    MIN_CORPUS_REPORTS,
    MIN_EXTRACTION_DOCUMENTS,
)
from intelligence.findings import registry
from intelligence.findings.contracts import DetectorValidation

BACKEND = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = BACKEND / "benchmark"


def test_the_benchmark_directory_holds_documentation_and_nothing_else():
    assert BENCHMARK_DIR.is_dir(), "the benchmark directory and its guide belong here"
    unexpected = [
        path.name
        for path in BENCHMARK_DIR.iterdir()
        if path.is_file() and path.suffix.lower() not in {".md", ".txt"}
    ]
    assert not unexpected, (
        f"{unexpected} in benchmark/. Annotated data is produced by clinicians "
        f"and is not committed here; a manufactured corpus would be "
        f"indistinguishable from real data in a few months."
    )


def test_no_file_in_the_tree_claims_to_be_an_annotated_corpus():
    """A corpus file is recognisable by its keys, and both the extraction and
    the reasoning corpora share them. Nothing in the repository may look like
    one - including under tests, where fixtures are built in memory precisely
    so that no file has to."""
    skip = {".venv", "node_modules", ".git", "__pycache__", ".pytest_cache",
            "staticfiles", "media", ".ruff_cache"}
    offenders = []
    for path in BACKEND.rglob("*.json"):
        if any(part in skip for part in path.parts):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict) and {"corpus_id", "items"} <= set(payload):
            offenders.append(str(path.relative_to(BACKEND)))
    assert not offenders, (
        f"{offenders} look like annotated corpora. Clinician annotations are "
        f"not committed to this repository."
    )


def test_with_no_corpus_nothing_is_measurable_and_the_tool_says_so():
    state = readiness(None, None)
    assert state["reasoning"]["corpus"] == "none"
    assert state["reasoning"]["promotable_codes"] == []
    assert str(MIN_CORPUS_REPORTS) in " ".join(state["reasoning"]["blocking"])

    assert state["extraction"]["corpus"] == "none"
    assert state["extraction"]["ready"] is False
    assert str(MIN_EXTRACTION_DOCUMENTS) in " ".join(
        state["extraction"]["blocking"]
    )


def test_and_so_every_detector_still_reports_that_it_has_never_been_measured():
    """The benchmark apparatus existing changes nothing about the claims the
    detectors make. Only data can do that."""
    for detector in registry.all_detectors():
        assert (
            detector.contract.validation_status is DetectorValidation.NOT_VALIDATED
        ), detector.contract.code
        assert detector.contract.validation_note.strip()
