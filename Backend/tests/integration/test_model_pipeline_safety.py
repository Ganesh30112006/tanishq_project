"""Guards on the training pipeline itself, for the ways it can go quietly wrong.

Every test here exists because the thing it checks actually broke, or would
have broken silently and produced a confident wrong number rather than an
error. None of them need the NHANES download: they either pin a constant, or
run a check against data constructed in the test.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ARTIFACTS = Path(__file__).resolve().parents[2] / "intelligence" / "_artifacts"


# --- units --------------------------------------------------------------
def test_training_converts_hba1c_with_the_same_constants_the_app_serves():
    """The training scale and the serving scale must be the same scale.

    NHANES publishes glycohemoglobin as NGSP percent. The application stores
    hba1c in IFCC mmol/mol. If the training pipeline and apps/common/units.py
    ever disagree about that conversion, a model fitted around 36 mmol/mol gets
    served a value of 5.5 - roughly six times too small, silently, with no error
    anywhere, producing a confidently wrong risk for every diabetic patient.
    """
    from apps.common.units import _LINEAR_RULES
    from intelligence.ml_service.nhanes_cohort import HBA1C_PCT_TO_MMOL_MOL

    factor, offset = _LINEAR_RULES[("hba1c", "%")]
    assert HBA1C_PCT_TO_MMOL_MOL == (float(factor), float(offset))


def test_the_app_canonical_hba1c_unit_is_what_training_produces():
    from apps.common.units import _CANONICAL_UNIT

    assert _CANONICAL_UNIT["hba1c"] == "mmol/mol"


# --- physiologic plausibility -------------------------------------------
def test_plausibility_bounds_reject_the_impossible_and_keep_the_merely_extreme():
    """Wide enough to keep real outliers, narrow enough to exclude artefacts.

    NHANES really does publish a glycohemoglobin of 2.0%, which converts to a
    NEGATIVE mmol/mol value. That is a haemoglobin variant defeating the assay,
    not a blood sugar. Trimming it matters twice over: it is a leverage point
    that bends the fitted coefficients, and the served ``valid_domain`` gate is
    derived from these same values, so training on impossible inputs widens the
    gate that is supposed to refuse impossible inputs from real patients.
    """
    from intelligence.ml_service.nhanes_cohort import PLAUSIBLE

    impossible = [
        ("hba1c", -1.64), ("hba1c", 0.0),
        ("bmi", 130.21), ("bmi", 3.0),
        ("systolic_bp", 0.0), ("hdl", 4.86),
    ]
    for name, value in impossible:
        lo, hi = PLAUSIBLE[name]
        assert not (lo <= value <= hi), f"{name}={value} should be rejected"

    # Genuinely extreme but real people, who must survive.
    real = [
        ("hba1c", 155.7), ("bmi", 66.9), ("bmi", 13.2),
        ("systolic_bp", 256.0), ("systolic_bp", 73.0), ("hdl", 0.31),
    ]
    for name, value in real:
        lo, hi = PLAUSIBLE[name]
        assert lo <= value <= hi, f"{name}={value} is real and must be kept"


# --- the shape check ------------------------------------------------------
def _frame(x, y):
    return pd.DataFrame({"feat": x, "y": y})


def test_monotonicity_check_catches_a_u_shape_that_sign_stability_cannot():
    """A U-shaped relationship has a stable sign and still misinforms.

    This is the BMI failure. Ten-year cardiovascular death is highest in the
    leanest group, lowest in the middle and high again at the top, because low
    weight in older adults is often illness. A linear coefficient fitted through
    that is positive and perfectly sign-stable, so every other check passes -
    and it tells a frail underweight patient that their weight is REDUCING their
    risk, which is the opposite of the truth.
    """
    from intelligence.ml_service.diagnostics import monotonicity_check

    rng = np.random.default_rng(0)
    # Five equal bins whose event rates go 20%, 5%, 5%, 5%, 25% - a clear U.
    x, y = [], []
    for band, rate in enumerate([0.20, 0.05, 0.05, 0.05, 0.25]):
        x.extend(rng.uniform(band, band + 1, 800))
        y.extend(rng.binomial(1, rate, 800))
    rows = monotonicity_check(_frame(x, y), ["feat"], {"feat": 1.0})
    row = rows[0]

    assert row["monotone"] is False
    assert "U-shaped" in row["shape"]
    # The coefficient is positive, so the model calls the LOW end protective -
    # and that end is the worst one in the data. That is the harm.
    assert row["misleads_protected_end"] is True


def test_monotonicity_check_passes_a_genuinely_monotone_feature():
    from intelligence.ml_service.diagnostics import monotonicity_check

    rng = np.random.default_rng(1)
    x, y = [], []
    for band, rate in enumerate([0.02, 0.04, 0.08, 0.16, 0.32]):
        x.extend(rng.uniform(band, band + 1, 800))
        y.extend(rng.binomial(1, rate, 800))
    row = monotonicity_check(_frame(x, y), ["feat"], {"feat": 1.0})[0]

    assert row["monotone"] is True
    assert row["misleads_protected_end"] is False


def test_a_mild_bend_at_the_safe_end_is_reported_but_not_condemned():
    """Blood pressure bends too, and that one is harmless.

    The very lowest readings carry slightly more risk than the next band up, so
    the relationship is not strictly monotone. But the low end is still the
    low-risk end, so telling a patient their low reading helps them is true. The
    check has to separate "there is a bend" from "the model calls its worst
    group its safest", or it would fire on blood pressure and gut the model's
    explanations for no benefit.
    """
    from intelligence.ml_service.diagnostics import monotonicity_check

    rng = np.random.default_rng(2)
    x, y = [], []
    for band, rate in enumerate([0.031, 0.024, 0.044, 0.046, 0.083]):
        x.extend(rng.uniform(band, band + 1, 3000))
        y.extend(rng.binomial(1, rate, 3000))
    row = monotonicity_check(_frame(x, y), ["feat"], {"feat": 1.0})[0]

    assert row["misleads_protected_end"] is False


def test_binary_features_are_monotone_by_definition():
    from intelligence.ml_service.diagnostics import monotonicity_check

    rng = np.random.default_rng(3)
    x = rng.integers(0, 2, 2000).astype(float)
    y = rng.binomial(1, 0.05 + 0.05 * x)
    row = monotonicity_check(_frame(x, y), ["feat"], {"feat": 1.0})[0]

    assert row["shape"] == "binary"
    assert row["monotone"] is True


# --- the shipped model card ----------------------------------------------
def _card(version):
    path = ARTIFACTS / f"cvd-{version}.meta.json"
    if not path.exists():
        pytest.skip(f"cvd-{version} not built in this checkout")
    return json.loads(path.read_text())


def test_the_shipped_model_states_its_comparison_with_age_as_a_measurement():
    """The card must report what was measured, not a sentence written by hand.

    "NOT statistically significant" was once a hardcoded string in the model
    card. It was true when it was written, it was never re-measured for the
    feature set that ended up shipping, and it would have gone on being printed
    long after it stopped being true. The verdict has to come from the interval.
    """
    card = _card("3.0.0")
    metrics = card["validation_metrics"]
    lo, hi = metrics["vs_age_alone"]["ci"]

    assert metrics["beats_age_alone"] == (lo > 0)
    claims_significant = "which excludes zero" in card["limitations"]
    assert claims_significant == metrics["beats_age_alone"]
    assert str(lo) in card["limitations"] or f"{lo:+.4f}" in card["limitations"]


def test_the_shipped_model_needs_no_laboratory_result():
    """The reach argument only holds if it is actually true of the artifact."""
    from apps.risk.feature_assembly import _LAB_ANALYTE

    card = _card("3.0.0")
    lab_backed = [f for f in card["feature_order"] if f in _LAB_ANALYTE]
    assert not lab_backed, (
        f"3.0.0 is documented as needing no laboratory result but requires "
        f"{lab_backed}"
    )


def test_bmi_is_absent_from_the_shipped_model():
    """Excluded on purpose; a later refit must not quietly bring it back.

    BMI's relationship to the outcome is U-shaped, so a linear coefficient
    points underweight patients the wrong way, and this system shows per-feature
    reasons to patients. It buys +0.0047 AUC with a lower confidence bound of
    +0.0001. That trade is not worth making, and it should not be re-made by
    accident.
    """
    assert "bmi" not in _card("3.0.0")["feature_order"]


def test_the_calibration_method_was_chosen_without_the_test_set():
    card = _card("3.0.0")
    metrics = card["validation_metrics"]
    selection = metrics["calibration_selection"]

    assert selection, "no record of how the calibration method was chosen"
    assert metrics["calibration"] == min(selection, key=lambda k: selection[k])
    assert card["calibration_version"].endswith(metrics["calibration"])
