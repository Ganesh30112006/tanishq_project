"""Data-quality subsystem (spec sections 17, 18, 48).

Deterministic rules produce quality *events*. Quality is reported as
completeness / consistency / validity / extraction reliability etc. - it is
explicitly NOT a medical health score. Anomaly detection FLAGS observations;
extreme clinical values are never auto-deleted (spec section 18).
"""
from __future__ import annotations

from django.db import models

from apps.common.enums import AnomalyMethod, ReviewStatus
from apps.common.models import UUIDTimeStampedModel
from apps.patients.models import Patient


class QualityDimension(models.TextChoices):
    COMPLETENESS = "COMPLETENESS", "Completeness"
    CONSISTENCY = "CONSISTENCY", "Consistency"
    VALIDITY = "VALIDITY", "Validity"
    EXTRACTION_RELIABILITY = "EXTRACTION_RELIABILITY", "Extraction reliability"
    SOURCE_QUALITY = "SOURCE_QUALITY", "Source quality"
    TIMELINESS = "TIMELINESS", "Timeliness"
    UNIQUENESS = "UNIQUENESS", "Uniqueness"


class DataQualityRule(UUIDTimeStampedModel):
    code = models.CharField(max_length=80, unique=True)
    dimension = models.CharField(max_length=32, choices=QualityDimension.choices)
    description = models.CharField(max_length=255)
    definition = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "dq_rule"


class DataQualityEvent(UUIDTimeStampedModel):
    subject_type = models.CharField(max_length=60)
    subject_id = models.CharField(max_length=64)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, null=True, blank=True, related_name="data_quality_events"
    )
    dimension = models.CharField(max_length=32, choices=QualityDimension.choices)
    rule = models.ForeignKey(
        DataQualityRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    passed = models.BooleanField()
    severity = models.CharField(max_length=16, blank=True)
    detail = models.JSONField(default=dict)
    evaluated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dq_event"
        indexes = [models.Index(fields=["subject_type", "subject_id"])]


class AnomalyFlag(UUIDTimeStampedModel):
    subject_type = models.CharField(max_length=60)
    subject_id = models.CharField(max_length=64)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, null=True, blank=True, related_name="anomaly_flags"
    )
    method = models.CharField(max_length=24, choices=AnomalyMethod.choices)
    anomaly_score = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    anomaly_status = models.CharField(max_length=16, default="FLAGGED")
    review_status = models.CharField(
        max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    detail = models.JSONField(default=dict)

    class Meta:
        db_table = "dq_anomaly_flag"
        indexes = [models.Index(fields=["subject_type", "subject_id"])]
