"""The timeline a detector is entitled to reason over.

"Abnormal now" and "abnormal for three months" are different clinical
statements, and only the second one is a chronic disease. Nothing in the
output distinguishes them - a finding that says "possible chronic kidney
disease" reads identically whether ninety days of history stood behind it or
nobody checked. So the check cannot live in a detector's good intentions.

A detector declares what timeline it needs. The evidence set declares what it
actually holds. The engine refuses to let the first exceed the second.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import ReferenceStatus
from intelligence.findings import registry
from intelligence.findings.contracts import (
    Confidence,
    DetectorValidation,
    EvidenceContract,
    EvidenceLevel,
    EvidenceRequirement,
    EvidenceTemporality,
)
from intelligence.findings.engine import detect
from intelligence.findings.evidence import EvidenceSet, Measurement
from intelligence.knowledge.findings import model as KB_MODEL

_BASE = {
    "version": "1.0.0",
    "label": "A label",
    "category": "renal",
    "required_evidence": (
        EvidenceRequirement(key="egfr", why="because"),
        EvidenceRequirement(key="creatinine", why="because"),
    ),
    "minimum_evidence": "two values",
    "valid_population": "adults",
    "confidence_policy": "stated",
    "validation_status": DetectorValidation.NOT_VALIDATED,
    "validation_note": "never measured here",
}


def _contract(**over) -> EvidenceContract:
    return EvidenceContract(**{**_BASE, **over})


# --- what a contract may declare ------------------------------------
def test_a_level_2_pattern_may_only_ever_be_a_single_report_observation():
    """Whether an abnormality persists is a level-3 question, so a level-2
    pattern is not allowed to ask it."""
    with pytest.raises(ValueError, match="observation on one report"):
        _contract(
            code="REDUCED_EGFR_PATTERN",
            level=EvidenceLevel.CLINICAL_ABNORMALITY,
            temporality=EvidenceTemporality.HISTORICAL,
            temporality_requirement="two values ninety days apart",
        )


def test_a_detector_needing_history_must_say_exactly_what_it_needs():
    """So the result can name what was missing rather than just failing."""
    with pytest.raises(ValueError, match="say exactly what timeline"):
        _contract(
            code="POSSIBLE_SOMETHING",
            level=EvidenceLevel.CONDITION_LIKELIHOOD,
            temporality=EvidenceTemporality.HISTORICAL,
        )


def test_a_single_report_contract_needs_no_requirement_statement():
    contract = _contract(
        code="REDUCED_EGFR_PATTERN", level=EvidenceLevel.CLINICAL_ABNORMALITY
    )
    assert contract.temporality is EvidenceTemporality.SINGLE_REPORT


def test_every_shipped_level_2_detector_reads_one_report():
    for detector in registry.by_level(EvidenceLevel.CLINICAL_ABNORMALITY):
        assert (
            detector.contract.temporality is EvidenceTemporality.SINGLE_REPORT
        ), detector.contract.code


# --- what an evidence set holds -------------------------------------
def test_a_set_built_from_one_report_holds_only_one_moment():
    evidence = EvidenceSet()
    assert evidence.supports(EvidenceTemporality.SINGLE_REPORT)
    assert not evidence.supports(EvidenceTemporality.REPEATED_MEASUREMENT)
    assert not evidence.supports(EvidenceTemporality.HISTORICAL)
    assert evidence.observation_window_days is None


# --- the engine holds a detector to its declared timeline -----------
_CHRONIC = EvidenceContract(
    code="POSSIBLE_TEST_CHRONIC_PATTERN_ONLY",
    version="1.0.0",
    level=EvidenceLevel.CONDITION_LIKELIHOOD,
    label="A test condition needing history",
    category="renal",
    required_evidence=(
        EvidenceRequirement(key="egfr", why="the abnormality"),
        EvidenceRequirement(key="creatinine", why="the corroboration"),
    ),
    minimum_evidence="two eGFR values",
    valid_population="adults",
    confidence_policy="stated",
    validation_status=DetectorValidation.NOT_VALIDATED,
    validation_note="a test fixture, never measured",
    temporality=EvidenceTemporality.HISTORICAL,
    temporality_requirement=(
        "Two eGFR values at least ninety days apart are needed before an "
        "abnormality can be called persistent."
    ),
)


class _AlwaysAsserts:
    """A detector that ignores the timeline. The engine must not let it."""

    contract = _CHRONIC

    def evaluate(self, evidence):
        from intelligence.findings.base import build_finding

        return build_finding(self.contract, confidence=Confidence.SUPPORTED)


@pytest.fixture
def _knowledge_for_the_fixture():
    """The knowledge dictionary refuses an unknown code, so register one."""
    entry = KB_MODEL.FindingKnowledge(
        code=_CHRONIC.code,
        canonical_name="A test condition",
        definition="A fixture.",
        plain_explanation="A fixture used only by the tests.",
        must_not_say=("Do not use this outside the tests.",),
    )
    from intelligence.knowledge import findings as KB

    KB._KNOWLEDGE[_CHRONIC.code] = entry
    try:
        yield
    finally:
        KB._KNOWLEDGE.pop(_CHRONIC.code, None)


def _one_report() -> EvidenceSet:
    return EvidenceSet(
        measurements={
            "egfr": Measurement(
                analyte="egfr", value=46.0, unit="mL/min/1.73m2",
                reference_low=60.0, reference_high=None,
                reference_text="> 60.0", reference_source="fallback-table",
                reference_kind="decision_threshold", status=ReferenceStatus.BELOW,
            )
        }
    )


def test_a_conclusion_is_downgraded_when_the_timeline_is_not_there(
    _knowledge_for_the_fixture,
):
    report = detect(_one_report(), detectors=[_AlwaysAsserts()])
    finding = report.findings[0]

    assert finding.confidence is Confidence.INSUFFICIENT
    assert not finding.asserts_anything
    assert _CHRONIC.temporality_requirement in finding.evidence_missing
    assert any("one point in time" in c for c in finding.caveats)


def test_a_downgraded_conclusion_is_not_built_upon(_knowledge_for_the_fixture):
    evidence = _one_report()
    detect(evidence, detectors=[_AlwaysAsserts()])
    assert _CHRONIC.code not in evidence.findings


def test_the_same_detector_is_allowed_through_once_the_history_exists(
    _knowledge_for_the_fixture,
):
    evidence = _one_report()
    evidence.available_temporality = frozenset({
        EvidenceTemporality.SINGLE_REPORT,
        EvidenceTemporality.REPEATED_MEASUREMENT,
        EvidenceTemporality.HISTORICAL,
    })
    evidence.observation_window_days = 120.0

    finding = detect(evidence, detectors=[_AlwaysAsserts()]).findings[0]
    assert finding.confidence is Confidence.SUPPORTED


def test_a_single_report_detector_is_never_touched_by_the_backstop():
    """The guard must not quietly suppress the ordinary case."""
    from intelligence.findings.renal import REDUCED_EGFR

    finding = detect(_one_report(), detectors=[REDUCED_EGFR]).findings[0]
    assert finding.code == "REDUCED_EGFR_PATTERN"
    assert finding.asserts_anything
