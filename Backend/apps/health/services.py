from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import transaction

from apps.common.enums import TRUSTWORTHY_CLINICAL_STATES, ClinicalDataState
from apps.common.errors import ValidationFailed
from apps.common.services import BaseService
from apps.health.models import HealthMeasurement
from apps.patients.models import Patient


class HealthMeasurementService(BaseService):
    @transaction.atomic
    def record(
        self,
        *,
        patient: Patient,
        kind: str,
        state: str,
        observed_at: dt.datetime,
        value: Decimal | float | int | None = None,
        unit: str = "",
        source: str = "",
        entered_by=None,
    ) -> HealthMeasurement:
        if state not in ClinicalDataState.values:
            raise ValidationFailed(f"Unknown clinical data state '{state}'.")
        if state in TRUSTWORTHY_CLINICAL_STATES and value is None:
            raise ValidationFailed("OBSERVED/DERIVED measurements require a value.")
        if value is not None and state not in TRUSTWORTHY_CLINICAL_STATES:
            raise ValidationFailed("Only OBSERVED/DERIVED measurements may carry a value.")

        measurement = HealthMeasurement(
            patient=patient,
            kind=kind,
            value_num=Decimal(str(value)) if value is not None else None,
            unit=unit,
            state=state,
            observed_at=observed_at,
            source=source,
            entered_by=entered_by,
        )
        measurement.full_clean(exclude=["provenance"])
        measurement.save()
        return measurement
