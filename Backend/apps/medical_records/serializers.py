from __future__ import annotations

from rest_framework import serializers

from apps.medical_records.models import Allergy, ClinicalNote, Condition, Medication, Symptom


class ConditionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)

    class Meta:
        model = Condition
        fields = ["id", "patient_id", "code", "label", "clinical_status", "onset_date", "created_at"]
        read_only_fields = ["id", "patient_id", "created_at"]


class ConditionWriteSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    code = serializers.CharField(max_length=32, required=False, allow_blank=True)
    label = serializers.CharField(max_length=255)
    clinical_status = serializers.ChoiceField(
        choices=Condition.ClinicalStatus.choices, default=Condition.ClinicalStatus.UNKNOWN
    )
    onset_date = serializers.DateField(required=False, allow_null=True)


class MedicationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)

    class Meta:
        model = Medication
        fields = [
            "id", "patient_id", "name", "dose", "route", "frequency",
            "status", "started_at", "stopped_at", "created_at",
        ]
        read_only_fields = ["id", "patient_id", "created_at"]


class MedicationWriteSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    name = serializers.CharField(max_length=200)
    dose = serializers.CharField(max_length=100, required=False, allow_blank=True)
    route = serializers.CharField(max_length=60, required=False, allow_blank=True)
    frequency = serializers.CharField(max_length=100, required=False, allow_blank=True)
    status = serializers.ChoiceField(
        choices=Medication.Status.choices, default=Medication.Status.UNKNOWN
    )
    started_at = serializers.DateField(required=False, allow_null=True)
    stopped_at = serializers.DateField(required=False, allow_null=True)


class AllergySerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)

    class Meta:
        model = Allergy
        fields = [
            "id", "patient_id", "substance", "reaction", "severity",
            "status", "onset_date", "created_at",
        ]
        read_only_fields = ["id", "patient_id", "created_at"]


class AllergyWriteSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    substance = serializers.CharField(max_length=200)
    reaction = serializers.CharField(max_length=255, required=False, allow_blank=True)
    severity = serializers.CharField(max_length=40, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=Allergy.Status.choices, default=Allergy.Status.ACTIVE)
    onset_date = serializers.DateField(required=False, allow_null=True)


class SymptomSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)

    class Meta:
        model = Symptom
        fields = ["id", "patient_id", "label", "severity", "state", "onset_at", "reported_at"]
        read_only_fields = ["id", "patient_id", "reported_at"]


class SymptomWriteSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    label = serializers.CharField(max_length=200)
    severity = serializers.CharField(max_length=40, required=False, allow_blank=True)
    onset_at = serializers.DateTimeField(required=False, allow_null=True)


class ClinicalNoteSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)
    author = serializers.CharField(source="author.get_username", read_only=True)
    amends_id = serializers.UUIDField(source="amends.public_id", read_only=True, allow_null=True)

    class Meta:
        model = ClinicalNote
        fields = ["id", "patient_id", "author", "note_type", "body", "authored_at", "amends_id"]
        read_only_fields = fields


class ClinicalNoteWriteSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    body = serializers.CharField()
    note_type = serializers.ChoiceField(
        choices=ClinicalNote.NoteType.choices, default=ClinicalNote.NoteType.PROGRESS
    )
    amends_id = serializers.UUIDField(required=False)
