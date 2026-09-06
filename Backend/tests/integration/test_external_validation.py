"""Validating on a population the model has never seen.

Two things make this fragile in ways ordinary tests would not catch.

The external cycles must stay *external*. The moment 2011-2014 leaks into the
training cohort, this stops being a validation and becomes a second test set
that the model was tuned on, and nothing in the metrics would look wrong.

And the horizon does not match. The model predicts 10-year risk; only five
years of follow-up exist for these cycles. Discrimination survives that,
calibration does not, and the difference is the whole reason this module
refuses to report a calibration slope. A future change that "fixes" the
mismatch by computing one anyway would produce a number that is wrong by
construction and reads as a finding.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from intelligence.ml_service import external_validation as ev
from intelligence.ml_service import nhanes_cohort, nhanes_download

ARTIFACTS = Path(__file__).resolve().parents[2] / "intelligence" / "_artifacts"


# --- the external set must stay external ---------------------------------
def test_the_validation_cycles_were_never_used_for_training():
    """A leakage guard on the survey cycles themselves."""
    development = {cycle[0] for cycle in nhanes_cohort.CYCLES}
    external = {cycle[0] for cycle in ev.EXTERNAL_CYCLES}

    assert not (development & external), (
        f"cycles {sorted(development & external)} appear in both the training "
        f"cohort and the external validation set"
    )
    # And every external cycle is strictly later, so this is a forward test.
    assert min(external) > max(development)


def test_the_downloader_keeps_the_two_sets_apart():
    development = {cycle[0] for cycle in nhanes_download.CYCLES}
    external = {cycle[0] for cycle in nhanes_download.EXTERNAL_CYCLES}
    assert not (development & external)


# --- the horizon mismatch is handled, not hidden -------------------------
def test_the_external_horizon_is_shorter_than_the_model_predicts():
    """If these ever match, the comment explaining the mismatch is stale."""
    assert ev.HORIZON_MONTHS == 60
    assert ev.HORIZON_MONTHS < nhanes_cohort.HORIZON_MONTHS


def test_the_report_refuses_calibration_and_says_why():
    path = ARTIFACTS / "cvd-3.1.0.external.json"
    if not path.exists():
        pytest.skip("external validation not run in this checkout")
    report = json.loads(path.read_text())

    assert report["calibration_reported"] is False
    assert report["calibration_not_reported_because"].strip()
    assert report["horizon_months"] < report["model_horizon_months"]
    # No calibration statistic may appear anywhere in the report.
    body = json.dumps(report).lower()
    assert "calibration_slope" not in body
    assert "calibration_in_the_large" not in body


def test_the_gradient_describes_ordering_and_not_levels():
    """Observed 5-year risk rises across predicted 10-year bands.

    The bands must be reported with both numbers visible so nobody reads the
    gap between them as miscalibration - it is the horizon, not the model.
    """
    rng = np.random.default_rng(0)
    p = rng.uniform(0.001, 0.30, 4000)
    y = rng.binomial(1, p / 2)          # 5-year risk, about half of 10-year
    rows = ev.risk_gradient(y, p, bins=5)

    assert len(rows) == 5
    assert all("mean_predicted_10y" in r and "observed_5y" in r for r in rows)
    assert all(r["observed_5y"] < r["mean_predicted_10y"] for r in rows[2:])
    assert rows[0]["observed_5y"] < rows[-1]["observed_5y"]


# --- small groups must not become quiet reassurance ----------------------
def _frame(groups):
    import pandas as pd

    rows = []
    for name, (n, events) in groups.items():
        for i in range(n):
            rows.append({"ethnicity": name, "y": 1 if i < events else 0})
    df = pd.DataFrame(rows)
    return df.reset_index(drop=True)


def test_a_group_with_too_few_deaths_is_flagged_not_reported_as_a_result():
    df = _frame({"Large": (2000, 60), "Tiny": (700, 7)})
    rng = np.random.default_rng(1)
    p = np.where(df.y == 1, rng.uniform(0.4, 0.9, len(df)),
                 rng.uniform(0.0, 0.5, len(df)))

    rows = {r["group"]: r for r in ev.discrimination_by_group(df, p, "ethnicity")}

    assert rows["Large"]["conclusion_supported"] is True
    assert rows["Tiny"]["conclusion_supported"] is False
    # An estimate is still produced - suppressing it entirely would hide the
    # gap rather than show it - but it carries the flag that says do not read
    # a conclusion into it.
    assert rows["Tiny"]["roc_auc"] is not None
    assert rows["Tiny"]["events"] == 7


def test_the_event_floor_for_a_conclusion_is_stated_rather_than_implicit():
    assert ev.MIN_EVENTS_FOR_A_CONCLUSION >= 25


def test_a_group_with_no_deaths_yields_no_auc_rather_than_a_crash():
    df = _frame({"NoDeaths": (300, 0), "Some": (900, 30)})
    p = np.linspace(0.01, 0.5, len(df))

    rows = {r["group"]: r for r in ev.discrimination_by_group(df, p, "ethnicity")}
    assert rows["NoDeaths"]["roc_auc"] is None
    assert rows["NoDeaths"]["conclusion_supported"] is False


# --- the shipped external report -----------------------------------------
def test_the_shipped_external_report_records_what_did_not_replicate():
    """Findings that fail to reproduce must survive into the record.

    Two development findings did not hold on the unseen population: refused
    patients were 2.05x sicker than served ones rather than 1.36x, and the
    low-blood-pressure breach that looked benign in development was 5.2x the
    served rate. Both rest on few deaths, which is the point - the development
    cohort was not enough to establish them either way.
    """
    path = ARTIFACTS / "cvd-3.1.0.external.json"
    if not path.exists():
        pytest.skip("external validation not run in this checkout")
    report = json.loads(path.read_text())

    replication = report["replication"]
    assert replication, "no replication check recorded"
    for row in replication:
        assert row["development"].strip()
        assert row["external"].strip()
        assert isinstance(row["replicates"], bool)


def test_the_external_report_does_not_claim_the_target_population():
    """It is a proxy, and the record has to say so.

    NHANES Non-Hispanic Asian participants are US residents and the category
    aggregates East, Southeast and South Asian. Reporting it as validation in
    the intended population would be the most consequential overstatement this
    project could make.
    """
    path = ARTIFACTS / "cvd-3.1.0.external.json"
    if not path.exists():
        pytest.skip("external validation not run in this checkout")
    report = json.loads(path.read_text())

    assert "NHANES" in report["population"]
    assert "never used in development" in report["population"]

    asian = [r for r in report["discrimination_by_ethnicity"]
             if "Asian" in r["group"]]
    if asian:
        # Whatever the estimate, it must not be presented as established.
        assert asian[0]["conclusion_supported"] is False, (
            "the Asian subgroup now has enough deaths to support a conclusion; "
            "update the report wording, which currently says it does not"
        )
