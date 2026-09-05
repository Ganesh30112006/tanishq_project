"""Vital-sign / point measurements.

Each row records not just a value but its :class:`ClinicalDataState` and the
timestamps needed for temporal reasoning (spec sections 9, 21). Rows are
immutable observations; a correction is a new row.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import ClinicalDataState
from apps.common.models import UUIDTimeStampedModel
from apps.patients.models import Patient


class MeasurementKind(models.TextChoices):
    SYSTOLIC_BP = "SYSTOLIC_BP", "Systolic blood pressure"
    DIASTOLIC_BP = "DIASTOLIC_BP", "Diastolic blood pressure"
    HEART_RATE = "HEART_RATE", "Heart rate"
    SPO2 = "SPO2", "Peripheral oxygen saturation"
    RESP_RATE = "RESP_RATE", "Respiratory rate"
    TEMPERATURE = "TEMPERATURE", "Body temperature"
    WEIGHT = "WEIGHT", "Body weight"
    HEIGHT = "HEIGHT", "Height"
    BMI = "BMI", "Body mass index"


class HealthMeasurement(UUIDTimeStampedModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="measurements")
    kind = models.CharField(max_length=20, choices=MeasurementKind.choices)
    value_num = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    state = models.CharField(max_length=16, choices=ClinicalDataState.choices)

    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=60, blank=True, help_text="Device, encounter, import batch")
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    provenance = models.ForeignKey(
        "medical_records.Provenance", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "health_measurement"
        indexes = [models.Index(fields=["patient", "kind", "observed_at"])]
        ordering = ["-observed_at"]
