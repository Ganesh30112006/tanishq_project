"""A new cohort must go through the same pipeline, judged by the same rules.

The value of every number in this project comes from the rules having been
fixed before the data arrived. The moment a cohort can be loaded in a way that
skips a check - or judged against a rule written after somebody saw how it
scored - the comparison between "what NHANES showed" and "what our own
population shows" stops meaning anything, and it stops meaning anything
silently.

So these tests guard the seams rather than the statistics: that a cohort has to
declare where it came from, that a frame missing the outcome cannot be scored
at all, and above all that the calibration rule is a property of the horizon
rather than a decision somebody makes per cohort.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from intelligence.ml_service import cohort_contract as CC
from intelligence.ml_service import external_validation as ev


def _spec(**changes):
    base = {
        "key": "test-cohort", "label": "A test cohort",
        "provenance": "written in a test", "country": "India",
        "examined": "2020", "outcome": "cardiovascular death",
        "outcome_source": "a death register", "horizon_months": 120,
        "ethnicity_scheme": "local categories", "role": CC.EXTERNAL,
        "consent_basis": "test data, nobody real",
    }
    base.update(changes)
    return CC.CohortSpec(**base)


def _frame(n=100, events=10, **drop):
    df = pd.DataFrame({
        "age": np.linspace(40, 79, n),
        "is_male": np.tile([0.0, 1.0], n // 2),
        "systolic_bp": np.linspace(95, 190, n),
        "current_smoker": np.tile([0.0, 1.0], n // 2),
        "y": [1] * events + [0] * (n - events),
        "sex": ["Male", "Female"] * (n // 2),
        "age_band": ["40-54"] * n,
        "ethnicity": ["Group A"] * n,
    })
    return df.drop(columns=[c for c, yes in drop.items() if yes])


FEATURES = ["age", "is_male", "systolic_bp", "current_smoker"]


# --- a cohort must declare what it is -----------------------------------
def test_a_cohort_must_declare_its_provenance():
    with pytest.raises(ValueError):
        _spec(provenance="   ")


def test_a_cohort_must_declare_how_the_outcome_was_ascertained():
    """Self-reported illness and a death register are not the same outcome."""
    with pytest.raises(ValueError):
        _spec(outcome_source="")


def test_a_cohort_must_declare_the_basis_on_which_it_may_be_used():
    with pytest.raises(ValueError):
        _spec(consent_basis="")


def test_a_cohort_must_declare_an_honest_role():
    with pytest.raises(ValueError):
        _spec(role="external-ish")


# --- the calibration rule belongs to the horizon, not to a judgement call -
def test_calibration_is_refused_when_the_cohort_is_shorter_than_the_model():
    reportable, why = CC.calibration_reportable(_spec(horizon_months=60), 120)
    assert reportable is False
    assert "wrong by construction" in why
    assert "too high" in why


def test_calibration_is_refused_when_the_cohort_is_longer_than_the_model():
    """The mirror case, which is easier to wave through and just as wrong."""
    reportable, why = CC.calibration_reportable(_spec(horizon_months=180), 120)
    assert reportable is False
    assert "too low" in why


def test_calibration_is_allowed_only_on_a_matching_horizon():
    reportable, why = CC.calibration_reportable(_spec(horizon_months=120), 120)
    assert reportable is True
    assert why == ""


def test_the_shipped_external_cohort_is_refused_calibration_by_that_rule():
    """Not by a hardcoded flag in the validation script."""
    reportable, why = CC.calibration_reportable(ev.SPEC, ev.MODEL_HORIZON_MONTHS)
    assert reportable is False
    assert why.strip()


# --- the contract check -------------------------------------------------
def test_a_complete_cohort_passes():
    assert CC.validate_cohort(_frame(), _spec(), FEATURES) == []


def test_a_cohort_with_no_outcome_column_cannot_be_scored():
    problems = CC.validate_cohort(_frame(y=True), _spec(), FEATURES)
    assert any(p.column == "y" and p.severity == "hard" for p in problems)


def test_a_cohort_missing_a_model_feature_cannot_be_scored():
    problems = CC.validate_cohort(_frame(systolic_bp=True), _spec(), FEATURES)
    assert any(p.column == "systolic_bp" and p.severity == "hard" for p in problems)


def test_a_cohort_with_no_events_is_refused_rather_than_scored():
    """An AUC computed on a cohort with no events is not a weak result."""
    problems = CC.validate_cohort(_frame(events=0), _spec(), FEATURES)
    assert any("no events" in p.message for p in problems)


def test_a_missing_outcome_is_not_treated_as_survival():
    df = _frame()
    df.loc[0, "y"] = np.nan
    problems = CC.validate_cohort(df, _spec(), FEATURES)
    assert any("not a person who survived" in p.message for p in problems)


def test_a_missing_group_column_removes_a_question_rather_than_stopping_the_run():
    """Subgroup reliability without a group column is no answer, not a bad one."""
    problems = CC.validate_cohort(_frame(ethnicity=True), _spec(), FEATURES)
    ethnicity = [p for p in problems if p.column == "ethnicity"]
    assert ethnicity and ethnicity[0].severity == "soft"
    assert not any(p.severity == "hard" for p in problems)


def test_all_problems_are_reported_at_once():
    problems = CC.validate_cohort(
        _frame(y=True, systolic_bp=True, ethnicity=True), _spec(), FEATURES
    )
    assert len({p.column for p in problems}) >= 3


# --- the registry -------------------------------------------------------
def test_an_unregistered_cohort_cannot_be_validated_against():
    with pytest.raises(KeyError) as excinfo:
        CC.get("some-hospital-extract")
    assert "declared provenance" in str(excinfo.value)


def test_a_cohort_key_cannot_be_quietly_redefined():
    """Two reports carrying one name must describe one population."""
    spec = _spec(key="stable-key")
    CC.register(spec, lambda: _frame())
    CC.register(spec, lambda: _frame())          # identical: fine

    with pytest.raises(ValueError) as excinfo:
        CC.register(_spec(key="stable-key", horizon_months=60), lambda: _frame())
    assert "different specification" in str(excinfo.value)


def test_the_nhanes_external_cohort_is_registered_and_declared_external():
    spec, loader = CC.get("nhanes-2011-2014")
    assert spec.role == CC.EXTERNAL
    assert callable(loader)
    assert spec.caveats, "a cohort used as a proxy must carry its caveats"


def test_the_validation_run_declares_its_horizon_from_the_spec():
    """One source for the horizon, so the two cannot drift apart."""
    assert ev.HORIZON_MONTHS == ev.SPEC.horizon_months
    assert ev.SPEC.horizon_months < ev.MODEL_HORIZON_MONTHS
