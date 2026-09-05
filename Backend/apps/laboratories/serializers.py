from __future__ import annotations

from rest_framework import serializers

from apps.common.enums import ClinicalDataState, ValidationStatus
from apps.laboratories.models import (
    Laboratory,
    LabOrder,
    LabResult,
    LabResultValidation,
    LabTechnician,
)


class LabResultValidationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabResultValidation
        fields = ["status", "note", "validated_at"]
        read_only_fields = fields


class LabResultSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    order_id = serializers.UUIDField(source="order.public_id", read_only=True)
    validations = LabResultValidationSerializer(many=True, read_only=True)

    class Meta:
        model = LabResult
        fields = [
            "id", "order_id", "analyte", "loinc_code",
            "value_raw", "unit_raw", "value_normalized", "unit_normalized",
            "conversion_rule_version", "state", "reference_low", "reference_high",
            "abnormal_flag", "method", "extraction_method",
            "observed_at", "reported_at", "recorded_at", "validations",
        ]
        read_only_fields = fields


class LabOrderSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)
    # Minimum-necessary identity: a technician must be able to tell which
    # specimen belongs to which requisition without gaining the clinical
    # record (spec section 41, `lab.patient_identity.read.min`).
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    laboratory = serializers.CharField(source="laboratory.code", read_only=True)
    results = LabResultSerializer(many=True, read_only=True)

    class Meta:
        model = LabOrder
        fields = [
            "id", "patient_id", "patient_name", "patient_mrn",
            "laboratory", "panel", "status",
            "requested_at", "collected_at", "results",
        ]
        read_only_fields = fields


class LabOrderCreateSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    panel = serializers.CharField(max_length=64)
    laboratory_id = serializers.UUIDField(required=False)
    collected_at = serializers.DateTimeField(required=False)


class LabResultEntrySerializer(serializers.Serializer):
    analyte = serializers.CharField(max_length=64)
    state = serializers.ChoiceField(choices=ClinicalDataState.choices)
    value = serializers.DecimalField(max_digits=18, decimal_places=6, required=False, allow_null=True)
    unit = serializers.CharField(max_length=32, required=False, allow_blank=True)
    observed_at = serializers.DateTimeField(required=False)
    method = serializers.CharField(max_length=64, required=False, allow_blank=True)


class LabResultValidateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ValidationStatus.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class LaboratorySerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Laboratory
        fields = ["id", "code", "name", "address", "is_active"]
        read_only_fields = fields


class LaboratoryWriteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=200)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)


class LabTechnicianSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    laboratory_id = serializers.UUIDField(source="laboratory.public_id", read_only=True)
    laboratory_code = serializers.CharField(source="laboratory.code", read_only=True)

    class Meta:
        model = LabTechnician
        fields = [
            "id", "email", "full_name", "laboratory_id", "laboratory_code",
            "employee_id", "is_active",
        ]
        read_only_fields = fields


class LabTechnicianWriteSerializer(serializers.Serializer):
    user_email = serializers.EmailField()
    laboratory_id = serializers.UUIDField()
    employee_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
