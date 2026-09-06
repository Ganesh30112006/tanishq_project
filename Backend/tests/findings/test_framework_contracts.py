"""The structural guards that stop a number becoming a diagnosis.

These do not test clinical logic. They test that the framework physically
refuses the shapes that cause harm: a level-2 finding named like a disease, a
level-3 conclusion drawn from one value, a risk model created by writing a
class, an unvalidated rule that does not admit it, a detector that invents its
own explanation.

Each of these is a rule somebody would otherwise have to remember on every
future detector, across fifteen body systems. Enforced here, it costs nothing
to remember.
"""
from __future__ import annotations

import pytest

from intelligence.findings import registry
from intelligence.findings.contracts import (
    DetectorValidation,
    EvidenceContract,
    EvidenceLevel,
    EvidenceRequirement,
)
from intelligence.knowledge import findings as KB

_REQ = (EvidenceRequirement(key="hemoglobin", why="because"),)
_BASE = {
    "version": "1.0.0",
    "label": "A label",
    "category": "hematology",
    "required_evidence": _REQ,
    "minimum_evidence": "one value",
    "valid_population": "adults",
    "confidence_policy": "stated",
    "validation_status": DetectorValidation.NOT_VALIDATED,
    "validation_note": "never measured here",
}


def _contract(**over) -> EvidenceContract:
    return EvidenceContract(**{**_BASE, **over})


# --- level 2 may not be named like a disease ------------------------
def test_a_level_2_code_must_be_named_as_a_pattern():
    with pytest.raises(ValueError, match="names a pattern, not a disease"):
        _contract(code="ANEMIA", level=EvidenceLevel.CLINICAL_ABNORMALITY)


def test_a_properly_named_level_2_pattern_is_accepted():
    contract = _contract(code="ANEMIA_PATTERN", level=EvidenceLevel.CLINICAL_ABNORMALITY)
    assert contract.identity == "ANEMIA_PATTERN:1.0.0"


# --- level 3 is hedged, needs a combination, needs review -----------
def test_a_level_3_code_must_be_hedged():
    with pytest.raises(ValueError, match="must be named as one"):
        _contract(
            code="IRON_DEFICIENCY_ANEMIA",
            level=EvidenceLevel.CONDITION_LIKELIHOOD,
            optional_evidence=(EvidenceRequirement(key="ferritin", why="x"),),
        )


def test_one_value_can_never_reach_a_condition_likelihood():
    """The rule that stops 'Hb 9.8 -> iron deficiency'."""
    with pytest.raises(ValueError, match="requires a combination of evidence"):
        _contract(
            code="POSSIBLE_IRON_DEFICIENCY",
            level=EvidenceLevel.CONDITION_LIKELIHOOD,
        )


def test_level_3_cannot_opt_out_of_human_review():
    with pytest.raises(ValueError, match="always requires human review"):
        _contract(
            code="POSSIBLE_IRON_DEFICIENCY",
            level=EvidenceLevel.CONDITION_LIKELIHOOD,
            optional_evidence=(EvidenceRequirement(key="ferritin", why="x"),),
            human_review_required=False,
        )


# --- level 4 cannot be created by writing a class -------------------
def test_a_risk_model_must_already_be_clinically_approved():
    """Governance lives in Django. A class here cannot mint a risk model."""
    with pytest.raises(ValueError, match="CLINICALLY_APPROVED"):
        _contract(
            code="CVD_10Y_RISK",
            level=EvidenceLevel.RISK_MODEL,
            optional_evidence=(EvidenceRequirement(key="age", why="x"),),
        )


# --- an unvalidated rule has to admit it ---------------------------
def test_an_unvalidated_detector_must_say_what_was_not_measured():
    with pytest.raises(ValueError, match="must say what has not been measured"):
        _contract(
            code="ANEMIA_PATTERN",
            level=EvidenceLevel.CLINICAL_ABNORMALITY,
            validation_note="   ",
        )


@pytest.mark.parametrize(
    "field", ["minimum_evidence", "valid_population", "confidence_policy"]
)
def test_the_contract_cannot_leave_its_policy_blank(field):
    with pytest.raises(ValueError, match=field):
        _contract(
            code="ANEMIA_PATTERN",
            level=EvidenceLevel.CLINICAL_ABNORMALITY,
            **{field: "  "},
        )


def test_evidence_mode_must_be_all_or_any():
    with pytest.raises(ValueError, match="required_evidence_mode"):
        _contract(
            code="ANEMIA_PATTERN",
            level=EvidenceLevel.CLINICAL_ABNORMALITY,
            required_evidence_mode="most",
        )


# --- the shipped registry obeys its own rules ----------------------
def test_every_registered_detector_declares_a_validation_status():
    for detector in registry.all_detectors():
        assert detector.contract.validation_status in DetectorValidation


def test_nothing_shipped_today_claims_to_be_validated():
    """No gold-standard set exists yet, so nothing may claim otherwise."""
    for detector in registry.all_detectors():
        assert detector.contract.validation_status is DetectorValidation.NOT_VALIDATED, (
            f"{detector.contract.code} claims "
            f"{detector.contract.validation_status.value}, but no annotated "
            f"benchmark has been built - see the Phase 4 gap"
        )
        assert detector.contract.validation_note.strip()


def test_no_registered_code_reads_as_a_bare_disease_name():
    banned = {
        "ANEMIA", "DIABETES", "CANCER", "INFECTION", "TUBERCULOSIS", "HIV",
        "HEPATITIS", "LEUKEMIA", "THALASSEMIA", "IRON_DEFICIENCY",
    }
    for code in registry.known_codes():
        assert code not in banned, f"{code} names a disease outright"


def test_no_registered_detector_maps_a_tumour_marker_to_a_cancer():
    """A standing prohibition, checked rather than remembered."""
    markers = {"cea", "ca-125", "ca125", "psa", "afp", "ca19-9"}
    for detector in registry.all_detectors():
        keys = {
            requirement.key.lower()
            for requirement in detector.contract.required_evidence
            + detector.contract.optional_evidence
        }
        assert not (keys & markers), (
            f"{detector.contract.code} reads a tumour marker; cancer needs "
            f"clinical context, imaging or pathology and a validated model"
        )


def test_every_registered_detector_has_an_entry_in_the_knowledge_dictionary():
    """A detector may not compose its own explanation."""
    for code in registry.known_codes():
        assert KB.get(code) is not None, f"{code} has no approved knowledge entry"


def test_every_knowledge_entry_states_what_must_not_be_said():
    for code in KB.known_codes():
        entry = KB.get(code)
        assert entry.plain_explanation.strip()
        assert entry.explanation_policy.strip()
        # The must-not-say list is what stops an explainer reaching for the
        # most alarming association it knows.
        assert entry.must_not_say, f"{code} places no bound on what may be said"


def test_registering_a_second_rule_under_one_code_is_refused():
    contract = _contract(code="TEST_ONLY_PATTERN", level=EvidenceLevel.CLINICAL_ABNORMALITY)

    class _Detector:
        def __init__(self, c):
            self.contract = c

        def evaluate(self, evidence):
            return None

    registry.register(_Detector(contract))
    registry.register(_Detector(contract))          # identical: fine
    try:
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_Detector(_contract(
                code="TEST_ONLY_PATTERN",
                level=EvidenceLevel.CLINICAL_ABNORMALITY,
                label="A different rule",
            )))
    finally:
        registry._DETECTORS.pop("TEST_ONLY_PATTERN", None)
