from __future__ import annotations

from rest_framework import serializers

from apps.alerts.models import Alert


class AlertSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)

    class Meta:
        model = Alert
        fields = [
            "id", "patient_id", "patient_name", "category", "severity", "title", "detail",
            "status", "source_workflow", "acknowledged_at", "resolved_at", "created_at",
        ]
        read_only_fields = [
            "id", "patient_id", "patient_name", "status", "acknowledged_at", "resolved_at", "created_at",
        ]


class AlertWriteSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    category = serializers.CharField(max_length=60)
    title = serializers.CharField(max_length=200)
    severity = serializers.ChoiceField(choices=Alert.Severity.choices, default=Alert.Severity.INFO)
    detail = serializers.CharField(required=False, allow_blank=True)
    source_workflow = serializers.CharField(max_length=60, required=False, allow_blank=True)
