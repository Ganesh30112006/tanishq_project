from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.common.enums import ClinicalDataState, DataSufficiency
from apps.risk.sufficiency import DataSufficiencyEngine, FeatureValue

NOW = timezone.now()

DEFINITION = {
    "required_features": [
        {"name": "glucose", "max_age_days": 90},
        {"name": "age", "max_age_days": 3650},
        {"name": "systolic_bp", "max_age_days": 30},
    ],
    "minimum_completeness": 1.0,
    "valid_domain": {"glucose": {"min": 1.0, "max": 40.0}},
}


def _fv(name, value, *, state=ClinicalDataState.OBSERVED, age_days=0):
    return FeatureValue(name=name, value=value, state=state, observed_at=NOW - dt.timedelta(days=age_days))


def test_all_present_and_fresh_is_sufficient():
    features = {
        "glucose": _fv("glucose", 5.4),
        "age": _fv("age", 51),
        "systolic_bp": _fv("systolic_bp", 128),
    }
    report = DataSufficiencyEngine().evaluate(definition=DEFINITION, features=features, now=NOW)
    assert report.status == DataSufficiency.SUFFICIENT


def test_missing_required_feature_blocks_and_is_named():
    features = {"glucose": _fv("glucose", 5.4), "age": _fv("age", 51)}
    report = DataSufficiencyEngine().evaluate(definition=DEFINITION, features=features, now=NOW)
    assert not report.is_sufficient
    assert "systolic_bp" in report.missing


def test_stale_value_is_not_treated_as_current():
    features = {
        "glucose": _fv("glucose", 5.4, age_days=400),
        "age": _fv("age", 51),
        "systolic_bp": _fv("systolic_bp", 128),
    }
    report = DataSufficiencyEngine().evaluate(definition=DEFINITION, features=features, now=NOW)
    assert "glucose" in report.stale
    assert not report.is_sufficient


def test_out_of_domain_value_is_flagged():
    features = {
        "glucose": _fv("glucose", 999),
        "age": _fv("age", 51),
        "systolic_bp": _fv("systolic_bp", 128),
    }
    report = DataSufficiencyEngine().evaluate(definition=DEFINITION, features=features, now=NOW)
    assert report.status == DataSufficiency.OUT_OF_DOMAIN
    assert "glucose" in report.out_of_domain


def test_conflicting_state_requires_review():
    features = {
        "glucose": _fv("glucose", None, state=ClinicalDataState.CONFLICTING),
        "age": _fv("age", 51),
        "systolic_bp": _fv("systolic_bp", 128),
    }
    report = DataSufficiencyEngine().evaluate(definition=DEFINITION, features=features, now=NOW)
    assert report.status == DataSufficiency.REVIEW_REQUIRED
    assert "glucose" in report.conflicting


def test_estimated_value_is_never_counted_as_observed():
    # A value carried in a non-trustworthy state must not satisfy a requirement.
    features = {
        "glucose": _fv("glucose", 5.4, state=ClinicalDataState.NOT_REPORTED),
        "age": _fv("age", 51),
        "systolic_bp": _fv("systolic_bp", 128),
    }
    report = DataSufficiencyEngine().evaluate(definition=DEFINITION, features=features, now=NOW)
    assert "glucose" in report.missing
