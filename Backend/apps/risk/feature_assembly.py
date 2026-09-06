"""Assemble model features from the authorized clinical record (spec sections 22, 51).

For each feature a model requires, this searches the structured record -
laboratory results and health measurements - for the most recent value that
is in a trustworthy clinical state, and returns it as a
:class:`~apps.risk.sufficiency.FeatureValue` carrying its ``observed_at`` so
the sufficiency engine can apply temporal-validity rules.

Nothing is imputed or estimated here. A feature that cannot be found is simply
absent from the result; the caller decides what to do about it.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

from apps.common.enums import TRUSTWORTHY_CLINICAL_STATES, ClinicalDataState
from apps.health.models import HealthMeasurement, MeasurementKind
from apps.laboratories.models import LabResult

# feature name -> health measurement kind
_VITAL_KIND: dict[str, str] = {
    "systolic_bp": MeasurementKind.SYSTOLIC_BP,
    "diastolic_bp": MeasurementKind.DIASTOLIC_BP,
    "heart_rate": MeasurementKind.HEART_RATE,
    "spo2": MeasurementKind.SPO2,
    "respiratory_rate": MeasurementKind.RESP_RATE,
    "temperature": MeasurementKind.TEMPERATURE,
    "weight": MeasurementKind.WEIGHT,
    "height": MeasurementKind.HEIGHT,
    "bmi": MeasurementKind.BMI,
    "current_smoker": MeasurementKind.SMOKING_STATUS,
}

# feature name -> laboratory analyte
_LAB_ANALYTE: dict[str, str] = {
    "glucose": "glucose",
    "fasting_glucose": "glucose",
    "hba1c": "hba1c",
    "total_cholesterol": "cholesterol",
    "hdl": "hdl",
    "ldl": "ldl",
    "triglycerides": "triglycerides",
    "creatinine": "creatinine",
}


@dataclass(slots=True)
class AssembledFeatures:
    values: dict[str, object] = field(default_factory=dict)  # name -> FeatureValue
    not_found: list[str] = field(default_factory=list)

    def lab_backed(self, name: str) -> bool:
        return name in _LAB_ANALYTE


class FeatureAssembler:
    def assemble(self, *, patient, feature_names: list[str], now: dt.datetime | None = None):
        from apps.risk.sufficiency import FeatureValue

        now = now or timezone.now()
        result = AssembledFeatures()

        for name in feature_names:
            fv: FeatureValue | None = None
            if name == "age":
                fv = self._age(patient, now)
            elif name == "is_male":
                fv = self._is_male(patient, now)
            elif name in _VITAL_KIND:
                fv = self._latest_vital(patient, name)
            elif name in _LAB_ANALYTE:
                fv = self._latest_lab(patient, name)

            if fv is None:
                result.not_found.append(name)
            else:
                result.values[name] = fv
        return result

    # -- sources -------------------------------------------------------
    @staticmethod
    def _age(patient, now: dt.datetime):
        from apps.risk.sufficiency import FeatureValue

        if not patient.date_of_birth:
            return None
        years = (now.date() - patient.date_of_birth).days / 365.25
        return FeatureValue(
            name="age", value=round(years, 2), state=ClinicalDataState.DERIVED, observed_at=now
        )

    @staticmethod
    def _is_male(patient, now: dt.datetime):
        """Sex as a model input, or nothing at all.

        Recorded sex is a strong cardiovascular predictor, so models use it.
        But INTERSEX and UNKNOWN are not "probably male": returning a value for
        them would be inventing a clinical fact about the patient. Returning
        None puts the feature in ``not_found``, and the sufficiency engine
        blocks the prediction - which is the correct outcome, because the model
        was never fitted on anyone the record describes this way.
        """
        from apps.patients.models import Sex
        from apps.risk.sufficiency import FeatureValue

        if patient.sex == Sex.MALE:
            value = Decimal("1")
        elif patient.sex == Sex.FEMALE:
            value = Decimal("0")
        else:
            return None
        return FeatureValue(
            name="is_male", value=value, state=ClinicalDataState.OBSERVED, observed_at=now
        )

    @staticmethod
    def _latest_vital(patient, name: str):
        from apps.risk.sufficiency import FeatureValue

        row = (
            HealthMeasurement.objects.filter(
                patient=patient, kind=_VITAL_KIND[name], state__in=TRUSTWORTHY_CLINICAL_STATES
            )
            .order_by("-observed_at")
            .first()
        )
        if row is None or row.value_num is None:
            return None
        return FeatureValue(
            name=name, value=row.value_num, state=row.state, observed_at=row.observed_at
        )

    @staticmethod
    def _latest_lab(patient, name: str):
        from apps.risk.sufficiency import FeatureValue

        row = (
            LabResult.objects.filter(
                order__patient=patient,
                analyte=_LAB_ANALYTE[name],
                state__in=TRUSTWORTHY_CLINICAL_STATES,
                superseded_by__isnull=True,
            )
            .order_by("-observed_at", "-recorded_at")
            .first()
        )
        if row is None:
            return None
        value = row.value_normalized if row.value_normalized is not None else row.value_raw
        if value is None or not isinstance(value, Decimal):
            return None
        observed = row.observed_at or row.reported_at or row.recorded_at
        return FeatureValue(name=name, value=value, state=row.state, observed_at=observed)
