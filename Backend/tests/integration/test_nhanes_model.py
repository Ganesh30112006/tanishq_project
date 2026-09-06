"""The NHANES-trained model, and the two ways it could quietly go wrong.

The model that ships now consumes recorded sex and is calibrated with Platt
scaling rather than isotonic regression. Both are small changes with sharp
edges:

* Sex is not a measurement that can be estimated. If the record does not say,
  the only safe answer is to refuse the prediction - never to pick the more
  common value and carry on.
* A Platt calibrator is a ``LogisticRegression``. Calling ``predict`` on one
  returns a class label, so a mis-applied calibrator turns every risk estimate
  into exactly 0.0 or 1.0 - a catastrophic output that still looks like a
  probability and would pass any "is it between 0 and 1" check.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone

from apps.common.enums import ClinicalDataState
from apps.health.models import HealthMeasurement, MeasurementKind
from apps.patients.models import Sex
from apps.risk.feature_assembly import FeatureAssembler
from apps.risk.sufficiency import DataSufficiencyEngine

pytestmark = pytest.mark.django_db

ARTIFACTS = Path(__file__).resolve().parents[2] / "intelligence" / "_artifacts"
FEATURES = ["age", "is_male", "systolic_bp", "glucose", "bmi"]


# --- sex is never guessed ------------------------------------------------
@pytest.mark.parametrize(
    "sex,expected",
    [(Sex.MALE, Decimal("1")), (Sex.FEMALE, Decimal("0"))],
)
def test_recorded_sex_becomes_the_feature(make_patient, sex, expected):
    patient = make_patient()
    patient.sex = sex
    patient.save(update_fields=["sex"])

    result = FeatureAssembler().assemble(patient=patient, feature_names=["is_male"])
    assert result.values["is_male"].value == expected
    assert result.not_found == []


@pytest.mark.parametrize("sex", [Sex.UNKNOWN, Sex.INTERSEX])
def test_unrecorded_sex_blocks_rather_than_assuming(make_patient, sex):
    """Guessing here would invent a clinical fact about a real person."""
    patient = make_patient()
    patient.sex = sex
    patient.save(update_fields=["sex"])

    result = FeatureAssembler().assemble(patient=patient, feature_names=["is_male"])
    assert "is_male" not in result.values
    assert result.not_found == ["is_male"]


def test_a_patient_without_recorded_sex_is_not_sufficient(make_patient):
    """The refusal has to survive all the way to the sufficiency verdict."""
    patient = make_patient()
    patient.sex = Sex.UNKNOWN
    patient.date_of_birth = timezone.now().date().replace(year=timezone.now().year - 60)
    patient.save(update_fields=["sex", "date_of_birth"])

    definition = {
        "required_features": [{"name": n, "max_age_days": 365} for n in ["age", "is_male"]],
        "minimum_completeness": 1.0,
        "max_data_age_days": 365,
        "valid_domain": {"age": {"min": 40, "max": 79}, "is_male": {"min": 0, "max": 1}},
    }
    assembled = FeatureAssembler().assemble(patient=patient, feature_names=["age", "is_male"])
    report = DataSufficiencyEngine().evaluate(
        definition=definition, features=assembled.values
    )
    assert not report.is_sufficient
    assert "is_male" in report.missing


# --- the calibrator is applied the way it was fitted ---------------------
def _bundle():
    path = ARTIFACTS / "cvd-2.3.0.joblib"
    if not path.exists():
        pytest.skip("NHANES artifact not built in this checkout")
    import joblib

    return joblib.load(path)


def test_the_shipped_bundle_declares_how_it_was_calibrated():
    bundle = _bundle()
    assert bundle["calibrator_kind"] == "platt"
    assert bundle["feature_order"] == FEATURES


def test_registry_defaults_to_isotonic_for_older_bundles():
    """Bundles trained before the Platt option existed carry no kind field."""
    from intelligence.ml_service import registry

    older = ARTIFACTS / "cvd-1.0.1.joblib"
    if not older.exists():
        pytest.skip("legacy artifact not present")
    loaded = registry.load("cvd", "1.0.1")
    assert loaded is not None
    assert loaded.calibrator_kind == "isotonic"


def test_platt_calibration_returns_a_probability_not_a_class_label():
    """The specific catastrophe: ``predict`` on a Platt calibrator gives 0 or 1.

    A calibrated risk that is exactly 0.0 or 1.0 for every patient would still
    be "a number between 0 and 1", so nothing downstream would complain. This
    asserts the values are genuinely graded.
    """
    from intelligence.ml_service.registry import LoadedModel
    from intelligence.ml_service.router import _calibrate

    bundle = _bundle()
    model = LoadedModel(
        task="cvd", version="2.3.0", feature_schema_version="fs-2.3.0",
        preprocessing_version=bundle["preprocessing_version"],
        calibration_version=bundle["calibration_version"],
        explanation_version=bundle["explanation_version"],
        feature_order=bundle["feature_order"], domain=bundle["domain"],
        estimator=bundle["estimator"], calibrator=bundle["calibrator"],
        calibrator_kind=bundle["calibrator_kind"], validation_metrics={},
    )

    calibrated = [_calibrate(model, raw) for raw in (0.01, 0.03, 0.08, 0.2, 0.5)]
    assert all(0.0 <= c <= 1.0 for c in calibrated)
    assert len(set(calibrated)) == len(calibrated), "calibrator collapsed distinct inputs"
    assert calibrated == sorted(calibrated), "calibration must preserve ordering"
    assert not any(c in (0.0, 1.0) for c in calibrated), "returned a class label, not a risk"


def test_calibration_matches_a_hand_computed_platt_step():
    bundle = _bundle()
    from intelligence.ml_service.registry import LoadedModel
    from intelligence.ml_service.router import _calibrate

    model = LoadedModel(
        task="cvd", version="2.3.0", feature_schema_version="fs-2.3.0",
        preprocessing_version="pp", calibration_version="cal", explanation_version="ex",
        feature_order=bundle["feature_order"], domain=bundle["domain"],
        estimator=bundle["estimator"], calibrator=bundle["calibrator"],
        calibrator_kind="platt", validation_metrics={},
    )
    raw = 0.035288
    expected = bundle["calibrator"].predict_proba(
        [[math.log(raw / (1 - raw))]]
    )[0][1]
    assert _calibrate(model, raw) == pytest.approx(expected, abs=1e-12)


# --- the model card says what was actually done --------------------------
def test_the_model_card_records_a_real_external_validation():
    """The patient-facing gate keys off this field, so it must not be aspirational."""
    meta_path = ARTIFACTS / "cvd-2.3.0.meta.json"
    if not meta_path.exists():
        pytest.skip("NHANES model card not built in this checkout")
    meta = json.loads(meta_path.read_text())

    assert meta["external_validation_dataset_version"], "gate would open on an empty string"
    assert "2007" in meta["external_validation_dataset_version"]
    assert meta["training_dataset_version"] != meta["external_validation_dataset_version"]
    assert meta["intended_use"]["prediction_horizon"] == "10 years"

    metrics = meta["validation_metrics"]
    assert metrics["events_test"] > 0
    assert metrics["leakage_check"].startswith("passed")
    # The card must not claim significance the confidence interval does not support.
    assert "NOT statistically significant" in meta["limitations"]


def test_out_of_domain_age_is_refused_not_extrapolated(make_patient):
    """The model was fitted on 40-79. A 31-year-old is not a small extrapolation."""
    meta_path = ARTIFACTS / "cvd-2.3.0.meta.json"
    if not meta_path.exists():
        pytest.skip("NHANES model card not built in this checkout")
    domain = json.loads(meta_path.read_text())["domain"]

    patient = make_patient()
    patient.sex = Sex.FEMALE
    today = timezone.now().date()
    patient.date_of_birth = today.replace(year=today.year - 31)
    patient.save(update_fields=["sex", "date_of_birth"])
    for kind, value in ((MeasurementKind.SYSTOLIC_BP, "118"), (MeasurementKind.BMI, "24")):
        HealthMeasurement.objects.create(
            patient=patient, kind=kind, value_num=Decimal(value), unit="",
            state=ClinicalDataState.OBSERVED, observed_at=timezone.now(),
        )

    definition = {
        "required_features": [
            {"name": n, "max_age_days": 365} for n in ["age", "is_male", "systolic_bp", "bmi"]
        ],
        "minimum_completeness": 1.0,
        "max_data_age_days": 365,
        "valid_domain": domain,
    }
    assembled = FeatureAssembler().assemble(
        patient=patient, feature_names=["age", "is_male", "systolic_bp", "bmi"]
    )
    report = DataSufficiencyEngine().evaluate(
        definition=definition, features=assembled.values
    )
    assert report.out_of_domain == ["age"]
    assert report.outcome_code() == "OUT_OF_DOMAIN"


# --- smoking, the feature that unlocked the better model -----------------
def test_smoking_status_is_a_dated_measurement_not_a_note(make_patient):
    """It goes through the same machinery as every other model input.

    Recording it as a free-text note would have put it outside the clinical
    data state, the observation date and the freshness rule - so a prediction
    could be built on an answer given years ago with nothing to flag it.
    """
    from apps.health.models import HealthMeasurement, MeasurementKind

    patient = make_patient()
    HealthMeasurement.objects.create(
        patient=patient,
        kind=MeasurementKind.SMOKING_STATUS,
        value_num=Decimal("1"),
        unit="",
        state=ClinicalDataState.OBSERVED,
        observed_at=timezone.now(),
    )
    result = FeatureAssembler().assemble(patient=patient, feature_names=["current_smoker"])
    assert result.values["current_smoker"].value == Decimal("1")
    assert result.values["current_smoker"].observed_at is not None


def test_an_unrecorded_smoking_status_blocks_rather_than_assuming_non_smoker(make_patient):
    """"Not recorded" is not "does not smoke".

    Defaulting to 0 would quietly under-estimate risk for every patient nobody
    had got round to asking, which is exactly the population least likely to
    have been asked.
    """
    patient = make_patient()
    result = FeatureAssembler().assemble(patient=patient, feature_names=["current_smoker"])
    assert "current_smoker" not in result.values
    assert result.not_found == ["current_smoker"]


def test_a_stale_smoking_answer_is_not_reused_indefinitely(make_patient):
    """Someone who smoked two years ago may have stopped."""
    import datetime as dt

    from apps.health.models import HealthMeasurement, MeasurementKind

    patient = make_patient()
    HealthMeasurement.objects.create(
        patient=patient,
        kind=MeasurementKind.SMOKING_STATUS,
        value_num=Decimal("1"),
        unit="",
        state=ClinicalDataState.OBSERVED,
        observed_at=timezone.now() - dt.timedelta(days=800),
    )
    definition = {
        "required_features": [{"name": "current_smoker", "max_age_days": 365}],
        "minimum_completeness": 1.0,
        "max_data_age_days": 365,
        "valid_domain": {"current_smoker": {"min": 0, "max": 1}},
    }
    assembled = FeatureAssembler().assemble(
        patient=patient, feature_names=["current_smoker"]
    )
    report = DataSufficiencyEngine().evaluate(
        definition=definition, features=assembled.values
    )
    assert report.stale == ["current_smoker"]
    assert not report.is_sufficient


@pytest.mark.parametrize("version", ["2.3.0", "2.4.0"])
def test_a_built_model_requires_only_sourceable_features(version):
    """Every required feature must be something the record can actually hold.

    A model requiring a feature the application cannot assemble is not
    deployable however good its metrics are - it would block every prediction.
    This is checked against the built artifact rather than the database, so it
    fails at build time instead of on the first patient.
    """
    from apps.risk.feature_assembly import _LAB_ANALYTE, _VITAL_KIND

    meta_path = ARTIFACTS / f"cvd-{version}.meta.json"
    if not meta_path.exists():
        pytest.skip(f"cvd-{version} not built in this checkout")
    meta = json.loads(meta_path.read_text())

    sourceable = set(_VITAL_KIND) | set(_LAB_ANALYTE) | {"age", "is_male"}
    unsourceable = [f for f in meta["feature_order"] if f not in sourceable]
    assert not unsourceable, (
        f"cvd-{version} requires {unsourceable}, which nothing in the record "
        f"can supply, so every prediction would be blocked"
    )
