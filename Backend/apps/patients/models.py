from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import AppendOnlyModel, UUIDTimeStampedModel


class Sex(models.TextChoices):
    FEMALE = "FEMALE", "Female"
    MALE = "MALE", "Male"
    INTERSEX = "INTERSEX", "Intersex"
    UNKNOWN = "UNKNOWN", "Unknown / not recorded"


class Patient(UUIDTimeStampedModel):
    """A patient record.

    ``user`` is nullable: a patient may exist in the record before they have a
    login. Clinical data hangs off this row; it is never hard-deleted.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient_profile",
    )
    mrn = models.CharField("medical record number", max_length=64, unique=True)
    given_name = models.CharField(max_length=100)
    family_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=10, choices=Sex.choices, default=Sex.UNKNOWN)
    phone = models.CharField(max_length=32, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "patients_patient"
        ordering = ["family_name", "given_name"]
        indexes = [
            models.Index(fields=["family_name", "given_name"]),
            models.Index(fields=["date_of_birth"]),
        ]

    def __str__(self) -> str:
        return f"{self.mrn} ({self.family_name}, {self.given_name})"

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}".strip()


class PatientIdentityCandidate(UUIDTimeStampedModel):
    """A scored potential-duplicate pair awaiting controlled review (spec section 19).

    Patient identities are NEVER merged automatically on name similarity. A
    candidate is created by the layered resolver; a human must confirm the
    pair is the same person before any merge.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        CONFIRMED_DISTINCT = "CONFIRMED_DISTINCT", "Confirmed distinct"
        MERGE_APPROVED = "MERGE_APPROVED", "Merge approved"
        MERGED = "MERGED", "Merged"

    class Tier(models.TextChoices):
        EXACT_IDENTIFIER = "EXACT_IDENTIFIER", "Exact identifier"
        NORMALIZED_IDENTIFIER = "NORMALIZED_IDENTIFIER", "Normalized identifier"
        DETERMINISTIC_COMPOSITE = "DETERMINISTIC_COMPOSITE", "Deterministic composite"
        SIMILARITY = "SIMILARITY", "Similarity"

    patient_a = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="identity_candidates_a")
    patient_b = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="identity_candidates_b")
    score = models.DecimalField(max_digits=5, decimal_places=4)
    tier = models.CharField(max_length=24, choices=Tier.choices)
    signals = models.JSONField(default=dict)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reconciliation_event = models.ForeignKey(
        "reconciliation.ReconciliationEvent", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="identity_candidates",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "patients_identity_candidate"
        constraints = [
            models.UniqueConstraint(fields=["patient_a", "patient_b"], name="uq_identity_candidate_pair")
        ]
        indexes = [models.Index(fields=["status", "tier"])]

    def __str__(self) -> str:
        return f"{self.patient_a_id}~{self.patient_b_id} ({self.tier} {self.score})"


class PatientMergeRecord(AppendOnlyModel):
    """Immutable record of a performed identity merge (spec sections 19, 44).

    A merge re-points clinical rows from ``merged_patient`` to
    ``surviving_patient`` and deactivates the merged record; nothing is
    destroyed.
    """

    candidate = models.ForeignKey(
        PatientIdentityCandidate, on_delete=models.PROTECT, related_name="merge_records"
    )
    surviving_patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="+")
    merged_patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="+")
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    moved_counts = models.JSONField(default=dict)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "patients_merge_record"
