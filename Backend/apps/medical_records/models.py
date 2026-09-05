"""Structured clinical record entities and data provenance.

Every important clinical fact carries a :class:`Provenance` row so a future
reviewer can answer "where did this value come from?" (spec section 10).
Clinical notes are append-only; corrections are addenda, not edits
(spec section 44).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import ClinicalDataState, ExtractionMethod, ValidationStatus
from apps.common.models import AppendOnlyModel, UUIDTimeStampedModel
from apps.patients.models import Patient


class Provenance(UUIDTimeStampedModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="provenance_records")
    source_report = models.ForeignKey(
        "reports.Report", on_delete=models.SET_NULL, null=True, blank=True, related_name="provenance_records"
    )
    source_page = models.PositiveIntegerField(null=True, blank=True)
    source_section = models.CharField(max_length=120, blank=True)
    original_text = models.TextField(blank=True)

    extraction_method = models.CharField(max_length=20, choices=ExtractionMethod.choices)
    extraction_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.PENDING
    )

    original_value = models.CharField(max_length=255, blank=True)
    normalized_value = models.CharField(max_length=255, blank=True)
    original_unit = models.CharField(max_length=32, blank=True)
    normalized_unit = models.CharField(max_length=32, blank=True)
    conversion_rule_version = models.CharField(max_length=32, blank=True)

    observed_at = models.DateTimeField(null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "records_provenance"
        indexes = [models.Index(fields=["patient", "recorded_at"])]


class MedicalHistory(UUIDTimeStampedModel):
    patient = models.OneToOneField(Patient, on_delete=models.PROTECT, related_name="medical_history")
    summary = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "records_medical_history"


class Condition(UUIDTimeStampedModel):
    class ClinicalStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RECURRENCE = "RECURRENCE", "Recurrence"
        REMISSION = "REMISSION", "Remission"
        RESOLVED = "RESOLVED", "Resolved"
        UNKNOWN = "UNKNOWN", "Unknown"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="conditions")
    code = models.CharField(max_length=32, blank=True, help_text="Coded term (e.g. ICD-10)")
    label = models.CharField(max_length=255)
    clinical_status = models.CharField(
        max_length=12, choices=ClinicalStatus.choices, default=ClinicalStatus.UNKNOWN
    )
    onset_date = models.DateField(null=True, blank=True)
    provenance = models.ForeignKey(
        Provenance, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "records_condition"
        indexes = [models.Index(fields=["patient", "clinical_status"])]


class Medication(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        STOPPED = "STOPPED", "Stopped"
        COMPLETED = "COMPLETED", "Completed"
        UNKNOWN = "UNKNOWN", "Unknown"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="medications")
    name = models.CharField(max_length=200)
    dose = models.CharField(max_length=100, blank=True)
    route = models.CharField(max_length=60, blank=True)
    frequency = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UNKNOWN)
    started_at = models.DateField(null=True, blank=True)
    stopped_at = models.DateField(null=True, blank=True)
    provenance = models.ForeignKey(
        Provenance, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "records_medication"


class Symptom(UUIDTimeStampedModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="symptoms")
    label = models.CharField(max_length=200)
    severity = models.CharField(max_length=40, blank=True)
    state = models.CharField(
        max_length=16, choices=ClinicalDataState.choices, default=ClinicalDataState.OBSERVED
    )
    onset_at = models.DateTimeField(null=True, blank=True)
    reported_at = models.DateTimeField(auto_now_add=True)
    provenance = models.ForeignKey(
        Provenance, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "records_symptom"


class Allergy(UUIDTimeStampedModel):
    """A patient-reported or clinically confirmed allergy/intolerance.

    Kept as its own entity (spec section 8 groups it with the rest of the
    structured clinical record) rather than folded into ``Condition`` so a
    reaction and its severity can be tracked without conflating "has a
    condition" with "reacts badly to a substance".
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RESOLVED = "RESOLVED", "Resolved"
        UNKNOWN = "UNKNOWN", "Unknown"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="allergies")
    substance = models.CharField(max_length=200)
    reaction = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    onset_date = models.DateField(null=True, blank=True)
    provenance = models.ForeignKey(
        Provenance, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "records_allergy"
        indexes = [models.Index(fields=["patient", "status"])]

    def __str__(self) -> str:
        return f"{self.substance} [{self.status}]"


class ClinicalNote(AppendOnlyModel):
    class NoteType(models.TextChoices):
        PROGRESS = "PROGRESS", "Progress note"
        ASSESSMENT = "ASSESSMENT", "Assessment"
        ADDENDUM = "ADDENDUM", "Addendum"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="clinical_notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_notes"
    )
    note_type = models.CharField(max_length=12, choices=NoteType.choices, default=NoteType.PROGRESS)
    body = models.TextField()
    authored_at = models.DateTimeField(auto_now_add=True)
    amends = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="addenda"
    )

    class Meta:
        db_table = "records_clinical_note"
        indexes = [models.Index(fields=["patient", "authored_at"])]
