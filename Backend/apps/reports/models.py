"""Report intelligence data model.

A medical report is structured knowledge, not just a file (spec section 11).
Extracted values keep their raw form, normalized form, per-stage confidence
and validation status. An LLM never writes a trusted value directly - see
:mod:`apps.reports.services` (spec section 12).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import (
    ClinicalDataState,
    CompletenessStatus,
    ExtractionMethod,
    ReportClass,
    ReportProcessingState,
    ValidationStatus,
)
from apps.common.models import UUIDTimeStampedModel, VersionedModel
from apps.patients.models import Patient


class ReportSchema(UUIDTimeStampedModel):
    """Versioned, configurable expected-schema for a report type (sections 14, 15)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    report_class = models.CharField(max_length=20, choices=ReportClass.choices)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    # definition: {expected_fields, required_fields, optional_fields, aliases,
    #              accepted_units, validation_rules, expected_sections,
    #              temporal_requirements}
    definition = models.JSONField(default=dict)

    class Meta:
        db_table = "reports_schema"
        constraints = [
            models.UniqueConstraint(
                fields=["report_class", "version"], name="uq_report_schema_version"
            )
        ]

    def __str__(self) -> str:
        return f"{self.report_class} v{self.version} ({self.status})"


class Report(VersionedModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="reports")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uploaded_reports"
    )

    report_class = models.CharField(max_length=20, choices=ReportClass.choices, blank=True)
    classification_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    schema = models.ForeignKey(
        ReportSchema, on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )

    processing_state = models.CharField(
        max_length=20, choices=ReportProcessingState.choices, default=ReportProcessingState.RECEIVED
    )
    completeness_status = models.CharField(
        max_length=12, choices=CompletenessStatus.choices, blank=True
    )
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.PENDING
    )
    review_reason = models.CharField(max_length=255, blank=True)

    facility = models.CharField(max_length=200, blank=True)
    ordering_provider = models.CharField(max_length=200, blank=True)
    specimen = models.CharField(max_length=120, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    reported_at = models.DateTimeField(null=True, blank=True)

    # Untrusted upload; stored privately, referenced by hash (spec section 39).
    source_file = models.FileField(upload_to="reports/%Y/%m/", max_length=255)
    original_filename = models.CharField(max_length=255, blank=True)
    file_sha256 = models.CharField(max_length=64, db_index=True)
    file_content_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)

    # Text obtained from OCR / a text upload. Populated by the pipeline, not the
    # client. Structured values are derived from this, never trusted from an LLM
    # without deterministic validation (spec section 12).
    extracted_text = models.TextField(blank=True)
    class_hint = models.CharField(
        max_length=20, choices=ReportClass.choices, blank=True,
        help_text="Report type asserted by the uploader; verified against the schema",
    )

    class Meta:
        db_table = "reports_report"
        indexes = [
            models.Index(fields=["patient", "report_class", "reported_at"]),
            models.Index(fields=["processing_state"]),
        ]

    def __str__(self) -> str:
        return f"Report {self.public_id} ({self.report_class or 'unclassified'})"


class ReportSection(UUIDTimeStampedModel):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=120)
    ordinal = models.PositiveIntegerField(default=0)
    raw_text = models.TextField(blank=True)
    detection_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )

    class Meta:
        db_table = "reports_section"
        ordering = ["ordinal"]


class ReportTest(UUIDTimeStampedModel):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="tests")
    section = models.ForeignKey(
        ReportSection, on_delete=models.SET_NULL, null=True, blank=True, related_name="tests"
    )
    name = models.CharField(max_length=120)
    loinc_code = models.CharField(max_length=20, blank=True)

    value_raw = models.CharField(max_length=120, blank=True)
    unit_raw = models.CharField(max_length=32, blank=True)
    value_normalized = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    unit_normalized = models.CharField(max_length=32, blank=True)
    conversion_rule_version = models.CharField(max_length=32, blank=True)
    reference_range = models.CharField(max_length=64, blank=True)
    abnormal_flag = models.CharField(max_length=8, blank=True)
    method = models.CharField(max_length=64, blank=True)

    state = models.CharField(
        max_length=16, choices=ClinicalDataState.choices, default=ClinicalDataState.PENDING
    )
    extraction_method = models.CharField(max_length=20, choices=ExtractionMethod.choices)
    ocr_confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    entity_confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    context_confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.PENDING
    )

    observed_at = models.DateTimeField(null=True, blank=True)
    provenance = models.ForeignKey(
        "medical_records.Provenance", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "reports_test"
        indexes = [models.Index(fields=["report", "name"])]


class ReportFinding(UUIDTimeStampedModel):
    class Category(models.TextChoices):
        FINDING = "FINDING", "Finding"
        INTERPRETATION = "INTERPRETATION", "Interpretation"
        CONCLUSION = "CONCLUSION", "Conclusion"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="findings")
    category = models.CharField(max_length=16, choices=Category.choices)
    text = models.TextField()
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    provenance = models.ForeignKey(
        "medical_records.Provenance", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "reports_finding"
