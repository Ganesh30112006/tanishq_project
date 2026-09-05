"""Laboratory workflow services.

Result entry performs *deterministic* unit normalization (spec section 16)
and requires the caller to state the :class:`ClinicalDataState` explicitly - a
blank value is never silently promoted to ``OBSERVED``.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import transaction

from apps.common.enums import ClinicalDataState, ExtractionMethod, ValidationStatus
from apps.common.errors import ValidationFailed
from apps.common.services import BaseService
from apps.common.units import convert
from apps.laboratories.models import LabOrder, LabResult, LabResultValidation

TRUSTWORTHY_WITH_VALUE = {ClinicalDataState.OBSERVED, ClinicalDataState.DERIVED}


class LabResultService(BaseService):
    @transaction.atomic
    def enter_result(
        self,
        *,
        order: LabOrder,
        analyte: str,
        state: str,
        value: Decimal | float | int | str | None = None,
        unit: str = "",
        observed_at: dt.datetime | None = None,
        method: str = "",
        entered_by=None,
    ) -> LabResult:
        if state not in ClinicalDataState.values:
            raise ValidationFailed(f"Unknown clinical data state '{state}'.")
        if state in TRUSTWORTHY_WITH_VALUE and value is None:
            raise ValidationFailed(
                "A value is required when the state is OBSERVED or DERIVED.",
                details={"analyte": analyte, "state": state},
            )
        if value is not None and state not in TRUSTWORTHY_WITH_VALUE:
            raise ValidationFailed(
                "A non-observed state must not carry a numeric value; record the "
                "reason instead (e.g. UNREADABLE, NOT_REPORTED).",
            )

        normalized_value = None
        normalized_unit = ""
        rule_version = ""
        if value is not None and unit:
            try:
                conversion = convert(value, unit, analyte)
                normalized_value = conversion.normalized_value
                normalized_unit = conversion.normalized_unit
                rule_version = conversion.rule_version
            except ValidationFailed:
                # Unknown analyte/unit: keep the raw value, flag for review.
                state = ClinicalDataState.AMBIGUOUS

        result = LabResult(
            order=order,
            analyte=analyte,
            value_raw=Decimal(str(value)) if value is not None else None,
            unit_raw=unit,
            value_normalized=normalized_value,
            unit_normalized=normalized_unit,
            conversion_rule_version=rule_version,
            state=state,
            method=method,
            extraction_method=ExtractionMethod.MANUAL_ENTRY,
            observed_at=observed_at,
            entered_by=entered_by,
        )
        result.full_clean(exclude=["supersedes"])
        result.save()

        # Deterministic data-quality + anomaly assessment (spec sections 17, 18).
        # Non-fatal: a check-side bug must never block clinical data entry.
        try:
            from apps.data_quality.assessors import assessor

            assessor.assess_lab_result(result)
            assessor.detect_anomalies(patient=order.patient, analyte=analyte)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("caresense.data_quality").exception("lab_result_quality_assessment_failed")
        return result

    @transaction.atomic
    def validate_result(
        self, *, lab_result: LabResult, status: str, validated_by=None, note: str = ""
    ) -> LabResultValidation:
        if status not in ValidationStatus.values:
            raise ValidationFailed(f"Unknown validation status '{status}'.")
        return LabResultValidation.objects.create(
            lab_result=lab_result, validated_by=validated_by, status=status, note=note
        )

    @transaction.atomic
    def correct_result(self, *, previous: LabResult, **new_values) -> LabResult:
        """Record a correction as a new row that supersedes ``previous``; the
        original is retained unchanged (spec section 44)."""
        corrected = self.enter_result(order=previous.order, **new_values)
        corrected.supersedes = previous
        corrected.save(update_fields=["supersedes"])
        return corrected
