"""Coverage, abstention, and the refusal that must not be silent.

The training battery answers "is the number accurate", computed on the people
the model could score. That population is not the population the tool is
pointed at, and the difference is the whole subject of this file.

The finding that produced it: of 16,097 adults in the target age range, 137
were refused because their systolic blood pressure sat above the validated
ceiling, and their 10-year cardiovascular death rate was 16.1% against 4.9%
for the people the model served. Every one of them received the same wording
as somebody refused for a harmless reason. The model still may not
extrapolate - but it may not be silent about what it saw either.
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from intelligence.ml_service import acceptance_criteria as AC
from intelligence.ml_service.clinical_validation import (
    classify_service,
    coverage_report,
    judge,
    recover_true_positives,
    refusal_by_group,
)

ARTIFACTS = Path(__file__).resolve().parents[2] / "intelligence" / "_artifacts"

DOMAIN = {
    "age": {"min": 40.0, "max": 79.0},
    "systolic_bp": {"min": 94.0, "max": 193.3333},
    "current_smoker": {"min": 0.0, "max": 1.0},
}
FEATURES = ["age", "systolic_bp", "current_smoker"]
#: Larger values of each carry more risk, as the fitted coefficients say.
DIRECTION = {"age": 1, "systolic_bp": 1, "current_smoker": 1}


def _people(rows):
    return pd.DataFrame(rows, columns=["age", "systolic_bp", "current_smoker", "y"])


# --- who gets served, and why not ---------------------------------------
def test_a_reading_above_the_ceiling_is_refused_on_the_higher_risk_side():
    df = _people([[60, 210.0, 0, 1]])
    service = classify_service(df, FEATURES, DOMAIN)

    assert not service.served.iloc[0]
    assert service.out_of_domain.iloc[0]
    assert service.breach_feature.iloc[0] == "systolic_bp"
    assert service.breach_side.iloc[0] == "above"

    report = coverage_report(df, service, DIRECTION)
    assert report["domain_breaches"][0]["higher_risk_side"] is True


def test_a_reading_below_the_floor_is_refused_but_is_not_the_dangerous_side():
    """Both are out of domain. Only one of them is the alarming one.

    Treating these identically is what the wording used to do, and it is why a
    blood pressure of 210 read to the patient as a shrug.
    """
    df = _people([[60, 80.0, 0, 0]])
    report = coverage_report(df, classify_service(df, FEATURES, DOMAIN), DIRECTION)

    breach = report["domain_breaches"][0]
    assert breach["side"] == "below"
    assert breach["higher_risk_side"] is False


def test_a_missing_input_is_a_different_refusal_from_an_out_of_range_one():
    df = _people([[60, np.nan, 0, 0], [60, 210.0, 0, 0], [60, 130.0, 0, 0]])
    service = classify_service(df, FEATURES, DOMAIN)

    assert list(service.missing) == [True, False, False]
    assert list(service.out_of_domain) == [False, True, False]
    assert list(service.served) == [False, False, True]


def test_coverage_reports_whether_refused_patients_are_sicker_than_served_ones():
    """The number that says whether the tool is silent where it is needed."""
    served = [[60, 130.0, 0, 0]] * 90 + [[60, 130.0, 0, 1]] * 10   # 10% event rate
    refused = [[60, 210.0, 0, 1]] * 8 + [[60, 210.0, 0, 0]] * 2    # 80% event rate
    df = _people(served + refused)

    report = coverage_report(df, classify_service(df, FEATURES, DOMAIN), DIRECTION)

    assert report["served"] == 100
    assert report["coverage"] == pytest.approx(100 / 110, abs=1e-3)
    assert report["served_event_rate"] == pytest.approx(0.10)
    assert report["refused_event_rate"] == pytest.approx(0.80)
    assert report["refused_risk_ratio"] == pytest.approx(8.0)


def test_refusal_rate_is_reported_per_group():
    df = _people([[60, 130.0, 0, 0]] * 8 + [[60, np.nan, 0, 0]] * 2)
    df["ethnicity"] = ["A"] * 5 + ["B"] * 5
    # Both refusals land in group B.
    df.loc[8:9, "ethnicity"] = "B"

    rows = {r["group"]: r for r in
            refusal_by_group(df, classify_service(df, FEATURES, DOMAIN), "ethnicity")}
    assert rows["A"]["refusal_rate"] == 0.0
    assert rows["B"]["refusal_rate"] == pytest.approx(0.4)


# --- clinical utility ----------------------------------------------------
def test_true_positives_are_recovered_exactly_from_an_older_model_card():
    """Net benefit and the flagged count determine the split exactly."""
    n, flagged, tp = 5351, 1833, 194
    fp = flagged - tp
    threshold = 0.05
    odds = threshold / (1 - threshold)
    row = {
        "threshold": threshold, "flagged": flagged,
        "net_benefit_model": round(tp / n - fp / n * odds, 5),
    }
    assert recover_true_positives(row, n) == tp


def test_a_recorded_true_positive_count_is_preferred_over_recovering_it():
    row = {"threshold": 0.05, "flagged": 100, "net_benefit_model": 0.0,
           "true_positives": 7}
    assert recover_true_positives(row, 1000) == 7


def test_an_inconsistent_row_yields_no_capacity_figure_rather_than_a_wrong_one():
    """Half a patient is not a capacity figure. Report nothing instead."""
    row = {"threshold": 0.05, "flagged": 100, "net_benefit_model": -9.0}
    assert recover_true_positives(row, 1000) is None


# --- the criteria themselves ---------------------------------------------
def _metrics(**over):
    base = {
        "primary": {"roc_auc": 0.77, "roc_auc_ci": [0.74, 0.79],
                    "calibration_slope": 0.95},
        "vs_age_alone": {"mean_diff": 0.024, "ci": [0.009, 0.040]},
        "beats_age_alone": True,
        "subgroup": [
            {"group": "Male", "events": 173, "roc_auc": 0.73,
             "roc_auc_ci": [0.70, 0.77], "mean_predicted": 0.062, "observed": 0.065},
        ],
    }
    base.update(over)
    return base


def _coverage(**over):
    base = {
        "target_population": 1000, "target_events": 50, "served": 950,
        "coverage": 0.95, "refused": 50, "refused_missing": 40,
        "refused_out_of_domain": 10, "served_event_rate": 0.05,
        "refused_event_rate": 0.06, "refused_risk_ratio": 1.2,
        "domain_breaches": [],
    }
    base.update(over)
    return base


def _groups(rates):
    return {"ethnicity": [
        {"group": name, "n": 1000, "refused": int(1000 * rate),
         "refusal_rate": rate} for name, rate in rates.items()
    ]}


def _by_key(results):
    return {r["key"]: r for r in results}


def test_every_criterion_the_judge_checks_is_declared_in_the_pre_registration():
    """A typo here would silently drop a criterion instead of failing it."""
    results = judge(_coverage(), _groups({"A": 0.05}), _metrics(),
                    {"beats_both": True, "threshold": 0.05,
                     "net_benefit_model": 0.02, "net_benefit_treat_all": 0.001},
                    directional_refusal_supported=True)
    assert {r["key"] for r in results} <= set(AC.CRITERIA_BY_KEY)
    assert len(results) == len(AC.CRITERIA)


def test_a_healthy_model_meets_every_criterion():
    results = judge(_coverage(), _groups({"A": 0.05, "B": 0.06}), _metrics(),
                    {"beats_both": True, "threshold": 0.05,
                     "net_benefit_model": 0.02, "net_benefit_treat_all": 0.001},
                    directional_refusal_supported=True)
    assert all(r["passed"] for r in results), [r["key"] for r in results if not r["passed"]]


def test_low_coverage_fails_even_when_the_model_is_accurate():
    results = _by_key(judge(
        _coverage(coverage=0.62), _groups({"A": 0.05}), _metrics(),
        {"beats_both": True, "threshold": 0.05, "net_benefit_model": 0.02,
         "net_benefit_treat_all": 0.001},
        directional_refusal_supported=True))
    assert results["coverage.overall"]["passed"] is False
    assert results["discrimination.above_chance"]["passed"] is True


def test_refusing_sicker_patients_than_it_serves_is_a_failure():
    results = _by_key(judge(
        _coverage(refused_risk_ratio=2.4), _groups({"A": 0.05}), _metrics(),
        {"beats_both": True, "threshold": 0.05, "net_benefit_model": 0.02,
         "net_benefit_treat_all": 0.001},
        directional_refusal_supported=True))
    assert results["coverage.refused_risk_ratio"]["passed"] is False


def test_unequal_coverage_between_groups_is_a_failure():
    results = _by_key(judge(
        _coverage(), _groups({"best": 0.05, "worst": 0.11}), _metrics(),
        {"beats_both": True, "threshold": 0.05, "net_benefit_model": 0.02,
         "net_benefit_treat_all": 0.001},
        directional_refusal_supported=True))
    check = results["coverage.group_disparity"]
    assert check["passed"] is False
    assert "worst" in check["observed"]


def test_a_dangerous_refusal_fails_unless_the_wording_distinguishes_it():
    coverage = _coverage(domain_breaches=[
        {"feature": "systolic_bp", "side": "above", "n": 137, "events": 22,
         "rate": 0.1606, "higher_risk_side": True},
    ])
    args = (_groups({"A": 0.05}), _metrics(),
            {"beats_both": True, "threshold": 0.05, "net_benefit_model": 0.02,
             "net_benefit_treat_all": 0.001})

    without = _by_key(judge(coverage, *args, directional_refusal_supported=False))
    assert without["coverage.no_silent_dangerous_refusal"]["passed"] is False

    with_wording = _by_key(judge(coverage, *args, directional_refusal_supported=True))
    assert with_wording["coverage.no_silent_dangerous_refusal"]["passed"] is True


def test_a_subgroup_no_better_than_chance_fails_a_model_that_looks_fine_overall():
    metrics = _metrics(subgroup=[
        {"group": "Age 70-79", "events": 142, "roc_auc": 0.52,
         "roc_auc_ci": [0.47, 0.58], "mean_predicted": 0.12, "observed": 0.12},
    ])
    results = _by_key(judge(
        _coverage(), _groups({"A": 0.05}), metrics,
        {"beats_both": True, "threshold": 0.05, "net_benefit_model": 0.02,
         "net_benefit_treat_all": 0.001},
        directional_refusal_supported=True))
    assert results["discrimination.above_chance"]["passed"] is True
    assert results["discrimination.subgroup_above_chance"]["passed"] is False


def test_a_small_subgroup_does_not_fail_the_model_on_noise():
    """Below the event floor an interval is too wide to mean anything."""
    metrics = _metrics(subgroup=[
        {"group": "Other/multiple", "events": 7, "roc_auc": 0.51,
         "roc_auc_ci": [0.30, 0.72], "mean_predicted": 0.04, "observed": 0.20},
    ])
    results = _by_key(judge(
        _coverage(), _groups({"A": 0.05}), metrics,
        {"beats_both": True, "threshold": 0.05, "net_benefit_model": 0.02,
         "net_benefit_treat_all": 0.001},
        directional_refusal_supported=True))
    assert results["discrimination.subgroup_above_chance"]["passed"] is True
    assert results["calibration.subgroup_error"]["passed"] is True
    # It must not read as a clean pass either. "Could not be assessed" and
    # "was assessed and was fine" are different claims.
    for key in ("discrimination.subgroup_above_chance", "calibration.subgroup_error"):
        assert "not assessed" in results[key]["observed"]


def test_understating_risk_in_a_subgroup_is_a_failure():
    metrics = _metrics(subgroup=[
        {"group": "Black non-Hispanic", "events": 67, "roc_auc": 0.72,
         "roc_auc_ci": [0.66, 0.79], "mean_predicted": 0.030, "observed": 0.061},
    ])
    results = _by_key(judge(
        _coverage(), _groups({"A": 0.05}), metrics,
        {"beats_both": True, "threshold": 0.05, "net_benefit_model": 0.02,
         "net_benefit_treat_all": 0.001},
        directional_refusal_supported=True))
    assert results["calibration.subgroup_error"]["passed"] is False


def test_every_criterion_states_why_it_matters():
    """A threshold nobody can justify gets moved the first time it fails."""
    for criterion in AC.CRITERIA:
        assert criterion.statement.strip()
        assert len(criterion.basis.strip()) > 40, criterion.key


# --- the shipped model's own report ---------------------------------------
def test_the_shipped_model_has_a_recorded_clinical_validation():
    path = ARTIFACTS / "cvd-3.1.0.clinical.json"
    if not path.exists():
        pytest.skip("clinical validation not run in this checkout")
    report = json.loads(path.read_text())

    assert report["criteria_version"] == AC.CRITERIA_VERSION
    assert report["passed"] == all(c["passed"] for c in report["criteria"])
    # Coverage is measured against the target population, which must be larger
    # than the training cohort - otherwise the question was not asked.
    assert report["coverage"]["target_population"] > report["coverage"]["served"]


# --- the served system, end to end ----------------------------------------
@pytest.mark.django_db
def test_registration_records_which_direction_each_input_moves_risk():
    from django.core.management import call_command

    from apps.risk.models import ModelVersion

    card_path = ARTIFACTS / "cvd-3.1.0.meta.json"
    if not card_path.exists():
        pytest.skip("cvd-3.1.0 not built in this checkout")
    card = json.loads(card_path.read_text())
    card["model_version"] = "9.9.9"
    card["feature_schema_version"] = "fs-9.9.9"
    tmp = ARTIFACTS / "cvd-9.9.9.meta.json"
    tmp.write_text(json.dumps(card))
    try:
        call_command("register_model", meta=str(tmp))
    finally:
        tmp.unlink(missing_ok=True)

    schema = ModelVersion.objects.get(version="9.9.9").feature_schema
    direction = schema.definition["risk_direction"]
    # Every one of these raises risk as it goes up, so every sign is positive
    # and a breach ABOVE the ceiling is the dangerous one.
    assert direction["systolic_bp"] == 1
    assert set(direction) == set(card["feature_order"])


@pytest.mark.django_db
def test_the_engine_records_which_bound_was_crossed_and_in_which_direction():
    from apps.common.enums import ClinicalDataState
    from apps.risk.sufficiency import DataSufficiencyEngine, FeatureValue

    definition = {
        "required_features": [{"name": "systolic_bp"}],
        "valid_domain": {"systolic_bp": {"min": 94.0, "max": 193.3333}},
        "risk_direction": {"systolic_bp": 1},
        "minimum_completeness": 1.0,
    }
    report = DataSufficiencyEngine().evaluate(
        definition=definition,
        features={"systolic_bp": FeatureValue(
            "systolic_bp", Decimal("204"), ClinicalDataState.OBSERVED,
            observed_at=dt.datetime.now(dt.UTC),
        )},
    )
    assert report.out_of_domain == ["systolic_bp"]
    breach = report.domain_breaches[0]
    assert breach["side"] == "above"
    assert breach["higher_risk_side"] is True
    assert breach["value"] == 204.0


@pytest.mark.django_db
def test_an_older_schema_without_directions_still_blocks_but_claims_nothing():
    """Absence of direction information must not become a claim of safety."""
    from apps.common.enums import ClinicalDataState
    from apps.risk.sufficiency import DataSufficiencyEngine, FeatureValue

    definition = {
        "required_features": [{"name": "systolic_bp"}],
        "valid_domain": {"systolic_bp": {"min": 94.0, "max": 193.3333}},
        "minimum_completeness": 1.0,
    }
    report = DataSufficiencyEngine().evaluate(
        definition=definition,
        features={"systolic_bp": FeatureValue(
            "systolic_bp", Decimal("204"), ClinicalDataState.OBSERVED,
            observed_at=dt.datetime.now(dt.UTC),
        )},
    )
    assert not report.is_sufficient
    assert report.domain_breaches[0]["higher_risk_side"] is False


@pytest.mark.django_db
def test_a_dangerous_reading_is_named_to_the_patient_not_shrugged_at(make_patient):
    """The wording a patient sees must differ from a harmless refusal.

    No risk estimate is produced, nothing is diagnosed, and no value is
    invented - the message repeats the reading already in the record and says
    to show it to a doctor.
    """
    from apps.risk.interpretation import describe_block
    from apps.risk.models import RiskAssessment

    patient = make_patient()
    dangerous = RiskAssessment(
        patient=patient, task="cvd", status=RiskAssessment.Status.BLOCKED,
        outcome_code="OUT_OF_DOMAIN",
        domain_breaches=[{"feature": "systolic_bp", "value": 204.0, "min": 94.0,
                          "max": 193.3333, "side": "above",
                          "higher_risk_side": True}],
    )
    harmless = RiskAssessment(
        patient=patient, task="cvd", status=RiskAssessment.Status.BLOCKED,
        outcome_code="OUT_OF_DOMAIN",
        domain_breaches=[{"feature": "systolic_bp", "value": 80.0, "min": 94.0,
                          "max": 193.3333, "side": "below",
                          "higher_risk_side": False}],
    )

    told = describe_block(dangerous)
    generic = describe_block(harmless)

    assert told["headline"] != generic["headline"]
    assert told["reading_needs_review"] is True
    assert generic["reading_needs_review"] is False
    assert "204" in told["detail"]
    assert "doctor" in told["detail"].lower()
    # It must not invent an estimate for a patient it just refused to score.
    assert "%" not in told["detail"]
