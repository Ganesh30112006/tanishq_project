"""Scheduled data-quality sweep (spec sections 17, 18, 47).

Assesses lab results that have not yet been evaluated and refreshes anomaly
flags. Idempotent: results already having a ``DataQualityEvent`` are skipped.
"""
from __future__ import annotations

from apps.jobs.runner import register


@register("dataquality.sweep")
def sweep(payload: dict) -> dict:
    from apps.data_quality.assessors import assessor
    from apps.data_quality.models import DataQualityEvent
    from apps.laboratories.models import LabResult

    limit = int(payload.get("limit", 500))
    assessed_ids = set(
        DataQualityEvent.objects.filter(subject_type="LabResult").values_list("subject_id", flat=True)
    )
    pending = (
        LabResult.objects.select_related("order")
        .order_by("-recorded_at")[: limit * 2]
    )

    assessed = 0
    anomalies = 0
    for lr in pending:
        if str(lr.public_id) in assessed_ids:
            continue
        assessor.assess_lab_result(lr)
        flags = assessor.detect_anomalies(patient=lr.order.patient, analyte=lr.analyte)
        anomalies += len(flags)
        assessed += 1
        if assessed >= limit:
            break
    return {"assessed": assessed, "anomaly_flags": anomalies}
