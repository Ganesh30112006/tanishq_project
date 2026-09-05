from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.common.enums import ModelLifecycleState, Role
from apps.risk.models import FeatureSchema, ModelVersion, RiskModel

pytestmark = pytest.mark.django_db


def test_register_model_from_meta_creates_a_draft(tmp_path):
    from intelligence.ml_service.train import build_demo_model

    build_demo_model("cvd", "1.0.0", tmp_path, seed=0)
    meta = tmp_path / "cvd-1.0.0.meta.json"

    call_command("register_model", meta=str(meta))

    schema = FeatureSchema.objects.get(task="cvd", version="fs-1.0.0")
    assert [f["name"] for f in schema.definition["required_features"]] == [
        "age", "glucose", "systolic_bp", "bmi", "hdl"
    ]

    mv = ModelVersion.objects.get(model_id="cvd-logreg", version="1.0.0")
    assert mv.lifecycle_state == ModelLifecycleState.DRAFT
    assert mv.calibration_version == "cal-1.0.0"
    assert "roc_auc" in mv.validation_metrics
    assert mv.intended_use["target_population"]
    # Registration alone never puts a model in front of clinicians.
    assert not RiskModel.objects.filter(task="cvd").exists()


def test_register_model_is_idempotent(tmp_path):
    from intelligence.ml_service.train import build_demo_model

    build_demo_model("cvd", "1.0.0", tmp_path, seed=0)
    meta = str(tmp_path / "cvd-1.0.0.meta.json")
    call_command("register_model", meta=meta)
    call_command("register_model", meta=meta)
    assert ModelVersion.objects.filter(model_id="cvd-logreg", version="1.0.0").count() == 1


def test_govern_model_walks_lifecycle_and_activates(tmp_path, make_user):
    from intelligence.ml_service.train import build_demo_model

    build_demo_model("cvd", "1.0.0", tmp_path, seed=0)
    call_command("register_model", meta=str(tmp_path / "cvd-1.0.0.meta.json"))
    approver = make_user(Role.ADMIN)

    for to_state in ("VALIDATION", "APPROVED_FOR_EVALUATION"):
        call_command(
            "govern_model", model="cvd-logreg", model_version="1.0.0",
            to=to_state, by=approver.email, reason=f"move to {to_state}",
        )
    call_command(
        "govern_model", model="cvd-logreg", model_version="1.0.0",
        to="APPROVED_FOR_CLINICAL_REVIEW", by=approver.email,
        reason="governance board sign-off", activate_task=True,
    )

    mv = ModelVersion.objects.get(model_id="cvd-logreg", version="1.0.0")
    assert mv.lifecycle_state == ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW
    assert mv.approved_by_id == approver.pk and mv.approved_at is not None
    rm = RiskModel.objects.get(task="cvd")
    assert rm.is_enabled and rm.active_version_id == mv.pk
    assert mv.lifecycle_events.count() == 3
