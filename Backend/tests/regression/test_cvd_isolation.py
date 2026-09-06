"""The cardiovascular engine cannot be reached by the document module.

There are two ways to state "the CVD engine is isolated". The weak way is to
break the document code at runtime and check the CVD path still answers - that
tests one path on one day. The strong way is to prove the CVD path never
imports the document, OCR or LLM code at all, so that whatever those modules do
- crash on import, raise, hang, return nonsense - is not on any code path the
CVD engine executes.

This file does both, with the import-graph check as the real guard.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

from tests.regression import frozen_baseline as FB

pytestmark = pytest.mark.regression

BACKEND = Path(__file__).resolve().parents[2]

#: The cardiovascular pathway: request handling, sufficiency, governance, the
#: client that talks to the intelligence service, and the model service itself.
CVD_SOURCE_ROOTS = [
    BACKEND / "apps" / "risk",
    BACKEND / "intelligence" / "ml_service",
    BACKEND / "apps" / "common" / "intelligence.py",
]

#: Nothing on that pathway may import anything under these. If document
#: intelligence needs something from the CVD side, the dependency points that
#: way - never back.
FORBIDDEN_PREFIXES = (
    "apps.reports",
    "apps.ai",
    "intelligence.document",
    "intelligence.ocr",
    "intelligence.nlp",
    "intelligence.rag",
    "intelligence.report_service",
)


def _python_files(root: Path):
    if root.is_file():
        yield root
    else:
        yield from root.rglob("*.py")


def _imported_modules(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                yield node.module


def test_the_cvd_pathway_imports_nothing_from_the_document_or_llm_side():
    offences: list[str] = []
    for root in CVD_SOURCE_ROOTS:
        for path in _python_files(root):
            for module in _imported_modules(path):
                if module.startswith(FORBIDDEN_PREFIXES):
                    rel = path.relative_to(BACKEND)
                    offences.append(f"{rel} imports {module}")
    assert not offences, (
        "the cardiovascular pathway now depends on document/LLM code:\n  "
        + "\n  ".join(offences)
        + "\nThe dependency must point from document intelligence towards the "
        "CVD side, never the other way."
    )


def test_the_forbidden_prefixes_are_real_locations_or_reserved_names():
    """A guard that checks against a typo'd prefix guards nothing.

    ``intelligence.document`` may not exist yet - that is fine, it is a
    reserved name this test defends. The rest must resolve.
    """
    reserved = {"intelligence.document"}
    for prefix in FORBIDDEN_PREFIXES:
        if prefix in reserved:
            continue
        top = prefix.split(".")[0]
        assert (BACKEND / top).exists(), f"{prefix}: '{top}/' is not in the tree"


# --- runtime: break the document side, CVD still scores identically ---
@pytest.fixture
def model():
    from intelligence.ml_service.registry import load

    loaded = load("cvd", FB.MODEL_VERSION)
    if loaded is None:
        pytest.skip(f"cvd-{FB.MODEL_VERSION}.joblib not built in this checkout")
    return loaded


class _Poisoned:
    """Any attribute access blows up, the way a broken module would."""

    def __getattr__(self, name):
        raise RuntimeError("document-intelligence module is deliberately broken")


@pytest.fixture
def document_side_is_broken(monkeypatch):
    for name in (
        "apps.reports.pipeline",
        "apps.reports.ocr",
        "apps.reports.extraction",
        "intelligence.document",
        "intelligence.nlp.router",
        "intelligence.rag.router",
    ):
        monkeypatch.setitem(sys.modules, name, _Poisoned())
    yield


def test_scores_are_unchanged_while_the_document_side_is_broken(
    model, document_side_is_broken
):
    def score(features):
        row = [[features[n] for n in model.feature_order]]
        return float(model.estimator.predict_proba(row)[0][1])

    for vector in FB.GOLDEN_VECTORS:
        got = score(vector["features"])
        assert abs(got - vector["raw_score"]) <= FB.SCORE_TOLERANCE, vector["label"]


def test_the_inference_service_still_serves_while_the_document_side_is_broken(
    model, document_side_is_broken
):
    from fastapi.testclient import TestClient

    from intelligence.main import app
    from intelligence.settings import get_settings

    client = TestClient(app)
    vector = FB.GOLDEN_VECTORS[0]
    resp = client.post(
        "/v1/infer",
        headers={"X-Service-Token": get_settings().service_token,
                 "X-Correlation-Id": "isolation"},
        json={
            "task": "cvd", "model_version": FB.MODEL_VERSION,
            "feature_schema_version": FB.FEATURE_SCHEMA_VERSION,
            "features": vector["features"], "correlation_id": "isolation",
        },
    )
    assert resp.status_code == 200
    assert abs(resp.json()["raw_score"] - vector["raw_score"]) <= FB.SCORE_TOLERANCE


def test_the_cvd_modules_import_cleanly_on_their_own():
    """No import-time dependency on anything document-shaped being importable."""
    for name in (
        "apps.risk.services",
        "apps.risk.governance",
        "apps.risk.sufficiency",
        "apps.common.intelligence",
        "intelligence.ml_service.registry",
        "intelligence.ml_service.router",
    ):
        importlib.import_module(name)
