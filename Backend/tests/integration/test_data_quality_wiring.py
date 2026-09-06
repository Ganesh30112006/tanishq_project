from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.common.enums import ClinicalDataState
from apps.data_quality.jobs import sweep
from apps.data_quality.models import AnomalyFlag, DataQualityEvent
from apps.laboratories.models import Laboratory, LabOrder
from apps.laboratories.services import LabResultService

pytestmark = pytest.mark.django_db

svc = LabResultService()


def _order(patient):
    lab = Laboratory.objects.create(name="L", code=f"L{patient.pk}")
    return LabOrder.objects.create(laboratory=lab, patient=patient, panel="GLUCOSE")


def test_entering_a_result_records_quality_events(make_patient):
    order = _order(make_patient())
    result = svc.enter_result(
        order=order, analyte="glucose", state=ClinicalDataState.OBSERVED, value="5.4", unit="mmol/L"
    )
    dims = set(
        DataQualityEvent.objects.filter(subject_id=str(result.public_id)).values_list(
            "dimension", flat=True
        )
    )
    assert {"VALIDITY", "CONSISTENCY", "TIMELINESS"} <= dims
    assert DataQualityEvent.objects.filter(
        subject_id=str(result.public_id), dimension="CONSISTENCY", passed=True
    ).exists()


def test_implausible_value_fails_consistency(make_patient):
    order = _order(make_patient())
    result = svc.enter_result(
        order=order, analyte="glucose", state=ClinicalDataState.OBSERVED, value="999", unit="mmol/L"
    )
    assert DataQualityEvent.objects.filter(
        subject_id=str(result.public_id), dimension="CONSISTENCY", passed=False
    ).exists()


def test_temporal_outlier_is_flagged_not_deleted(make_patient):
    patient = make_patient()
    order = _order(patient)
    now = timezone.now()
    for i, v in enumerate(["5.1", "5.3", "5.2", "5.4"]):
        r = svc.enter_result(order=order, analyte="glucose", state=ClinicalDataState.OBSERVED,
                             value=v, unit="mmol/L")
        r.observed_at = now - dt.timedelta(days=30 - i)
        r.save(update_fields=["observed_at"])
    spike = svc.enter_result(order=order, analyte="glucose", state=ClinicalDataState.OBSERVED,
                             value="19.0", unit="mmol/L")
    spike.observed_at = now
    spike.save(update_fields=["observed_at"])

    from apps.data_quality.assessors import assessor

    flags = assessor.detect_anomalies(patient=patient, analyte="glucose")
    assert flags
    assert AnomalyFlag.objects.filter(subject_id=str(spike.public_id)).exists()
    # The extreme value is still present - flagged, never removed (spec section 18).
    spike.refresh_from_db()
    assert spike.value_normalized == Decimal("19.000000")


def test_sweep_job_is_idempotent(make_patient):
    order = _order(make_patient())
    svc.enter_result(order=order, analyte="glucose", state=ClinicalDataState.OBSERVED,
                     value="5.4", unit="mmol/L")
    sweep({"limit": 100})
    second = sweep({"limit": 100})
    # Everything was already assessed on entry / first sweep.
    assert second["assessed"] == 0
