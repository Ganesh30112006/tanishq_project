"""Deterministic quality + anomaly assessment for stored clinical values
(spec sections 17, 18).

``assess_lab_result`` writes ``DataQualityEvent`` rows for one lab result
(validity, unit, timeliness, plausibility). ``detect_anomalies`` computes IQR
and MAD flags over a patient's history for an analyte and writes
``AnomalyFlag`` rows - it only FLAGS; a statistical outlier may be genuine and
is never deleted or altered.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.common.enums import AnomalyMethod
from apps.common.services import BaseService
from apps.data_quality.models import AnomalyFlag, DataQualityEvent, QualityDimension
from apps.data_quality.services import iqr_bounds, mad_score

logger = logging.getLogger("caresense.data_quality")

# Wide plausibility bounds in canonical units. NOT clinical reference ranges -
# these only catch impossible / transcription-error values.
PLAUSIBILITY: dict[str, tuple[float, float]] = {
    "glucose": (1.0, 60.0),
    "hba1c": (10.0, 200.0),
    "cholesterol": (0.5, 25.0),
    "hdl": (0.1, 6.0),
    "ldl": (0.1, 20.0),
    "triglycerides": (0.1, 40.0),
    "creatinine": (5.0, 2000.0),
    "hemoglobin": (20.0, 260.0),
}

MAD_THRESHOLD = 3.5
MIN_HISTORY = 4


class ClinicalQualityAssessor(BaseService):
    @transaction.atomic
    def assess_lab_result(self, lab_result) -> list[DataQualityEvent]:
        patient = lab_result.order.patient
        subject = ("LabResult", str(lab_result.public_id))
        events: list[DataQualityEvent] = []

        def emit(dimension: str, passed: bool, detail: dict) -> None:
            events.append(
                DataQualityEvent.objects.create(
                    subject_type=subject[0], subject_id=subject[1], patient=patient,
                    dimension=dimension, passed=passed, severity="" if passed else "warning",
                    detail=detail,
                )
            )

        value = lab_result.value_normalized
        emit(
            QualityDimension.VALIDITY,
            value is not None,
            {"analyte": lab_result.analyte, "has_normalized_value": value is not None},
        )
        emit(
            QualityDimension.EXTRACTION_RELIABILITY,
            bool(lab_result.unit_normalized) or value is None,
            {"unit_normalized": lab_result.unit_normalized},
        )
        emit(
            QualityDimension.TIMELINESS,
            lab_result.observed_at is not None,
            {"observed_at": lab_result.observed_at.isoformat() if lab_result.observed_at else None},
        )

        if value is not None:
            lo, hi = PLAUSIBILITY.get(lab_result.analyte, (None, None))
            if lo is not None:
                try:
                    fv = float(value)
                    within = lo <= fv <= hi
                except (TypeError, ValueError):
                    within = False
                    fv = None
                emit(
                    QualityDimension.CONSISTENCY,
                    within,
                    {"analyte": lab_result.analyte, "value": fv, "plausible_range": [lo, hi]},
                )
        return events

    @transaction.atomic
    def detect_anomalies(self, *, patient, analyte: str) -> list[AnomalyFlag]:
        from apps.laboratories.models import LabResult

        rows = list(
            LabResult.objects.filter(
                order__patient=patient, analyte=analyte,
                value_normalized__isnull=False, superseded_by__isnull=True,
            ).order_by("observed_at", "recorded_at")
        )
        if len(rows) < MIN_HISTORY:
            return []

        values = [float(r.value_normalized) for r in rows]
        latest = rows[-1]
        latest_value = values[-1]
        history = values[:-1]

        flags: list[AnomalyFlag] = []
        lo, hi = iqr_bounds(history)
        if latest_value < lo or latest_value > hi:
            flags.append(self._flag(latest, patient, AnomalyMethod.IQR, latest_value,
                                    {"fence": [lo, hi]}))
        z = mad_score(latest_value, history)
        if abs(z) > MAD_THRESHOLD:
            flags.append(self._flag(latest, patient, AnomalyMethod.MAD, abs(z),
                                    {"modified_z": round(z, 3), "threshold": MAD_THRESHOLD}))
        return flags

    def _flag(self, lab_result, patient, method: str, score: float, detail: dict) -> AnomalyFlag:
        existing = AnomalyFlag.objects.filter(
            subject_type="LabResult", subject_id=str(lab_result.public_id), method=method,
        ).first()
        if existing:
            return existing
        detail = {**detail, "analyte": lab_result.analyte, "value": float(lab_result.value_normalized)}
        return AnomalyFlag.objects.create(
            subject_type="LabResult", subject_id=str(lab_result.public_id), patient=patient,
            method=method, anomaly_score=_dec(score), detail=detail,
        )


def _dec(value: float):
    try:
        return Decimal(str(round(value, 6)))
    except InvalidOperation:  # pragma: no cover
        return None


assessor = ClinicalQualityAssessor()
