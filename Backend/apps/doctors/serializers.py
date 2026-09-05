from __future__ import annotations

from rest_framework import serializers

from apps.doctors.models import Doctor, DoctorPatientAssignment


class DoctorSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = Doctor
        fields = ["id", "email", "full_name", "registration_number", "specialty", "is_active"]
        read_only_fields = fields


class AssignmentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="patient.mrn", read_only=True)
    doctor_id = serializers.UUIDField(source="doctor.public_id", read_only=True)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)

    class Meta:
        model = DoctorPatientAssignment
        fields = [
            "id", "doctor_id", "doctor_name", "patient_id", "patient_name",
            "patient_mrn", "status", "reason", "assigned_at", "ended_at",
        ]
        read_only_fields = fields


class DoctorWriteSerializer(serializers.Serializer):
    user_email = serializers.EmailField()
    registration_number = serializers.CharField(max_length=64)
    specialty = serializers.CharField(max_length=120, required=False, allow_blank=True)


class AssignmentCreateSerializer(serializers.Serializer):
    doctor_id = serializers.UUIDField()
    patient_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class AssignmentEndSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
