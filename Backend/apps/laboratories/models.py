from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import ClinicalDataState, ExtractionMethod, ValidationStatus
from apps.common.models import UUIDTimeStampedModel, VersionedModel
from apps.patients.models import Patient


class Laboratory(UUIDTimeStampedModel):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=32, unique=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "lab_laboratory"

    def __str__(self) -> str:
        return self.code


class LabTechnician(UUIDTimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lab_technician_profile"
    )
    laboratory = models.ForeignKey(Laboratory, on_delete=models.PROTECT, related_name="technicians")
    employee_id = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "lab_technician"

    def __str__(self) -> str:
        return f"{self.user.get_username()}@{self.laboratory.code}"


class LabOrder(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        COLLECTED = "COLLECTED", "Specimen collected"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        RESULTED = "RESULTED", "Resulted"
        VALIDATED = "VALIDATED", "Validated"
        CANCELLED = "CANCELLED", "Cancelled"

    OPEN_STATUSES = (
        Status.REQUESTED,
        Status.COLLECTED,
        Status.IN_PROGRESS,
        Status.RESULTED,
    )

    laboratory = models.ForeignKey(Laboratory, on_delete=models.PROTECT, related_name="orders")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="lab_orders")
    ordered_by = models.ForeignKey(
        "doctors.Doctor", on_delete=models.SET_NULL, null=True, blank=True, related_name="lab_orders"
    )
    panel = models.CharField(max_length=64, help_text="Requested panel / report class")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)
    collected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "lab_order"
        indexes = [models.Index(fields=["laboratory", "patient", "status"])]

    def __str__(self) -> str:
        return f"Order {self.public_id} ({self.panel})"


class LabResult(VersionedModel):
    """A single analyte result.

    Corrections never overwrite: a corrected value is a new row whose
    ``supersedes`` points at the prior one (spec sections 8, 44).
    """

    order = models.ForeignKey(LabOrder, on_delete=models.PROTECT, related_name="results")
    analyte = models.CharField(max_length=64)
    loinc_code = models.CharField(max_length=20, blank=True)

    value_raw = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    unit_raw = models.CharField(max_length=32, blank=True)
    value_text = models.CharField(max_length=255, blank=True)

    value_normalized = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    unit_normalized = models.CharField(max_length=32, blank=True)
    conversion_rule_version = models.CharField(max_length=32, blank=True)

    state = models.CharField(max_length=16, choices=ClinicalDataState.choices)
    reference_low = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    reference_high = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    abnormal_flag = models.CharField(max_length=8, blank=True)
    method = models.CharField(max_length=64, blank=True)
    extraction_method = models.CharField(
        max_length=20, choices=ExtractionMethod.choices, default=ExtractionMethod.MANUAL_ENTRY
    )

    observed_at = models.DateTimeField(null=True, blank=True)
    reported_at = models.DateTimeField(null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    supersedes = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by"
    )

    class Meta:
        db_table = "lab_result"
        indexes = [models.Index(fields=["order", "analyte", "observed_at"])]

    def __str__(self) -> str:
        return f"{self.analyte}={self.value_normalized or self.value_raw} [{self.state}]"


class LabResultValidation(UUIDTimeStampedModel):
    lab_result = models.ForeignKey(LabResult, on_delete=models.PROTECT, related_name="validations")
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    status = models.CharField(max_length=16, choices=ValidationStatus.choices)
    note = models.CharField(max_length=255, blank=True)
    validated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "lab_result_validation"
