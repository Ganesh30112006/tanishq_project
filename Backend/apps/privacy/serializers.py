from __future__ import annotations

from rest_framework import serializers

from apps.privacy.models import ConsentPurpose, ErasureRequest


class ConsentWriteSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=ConsentPurpose.choices)
    granted = serializers.BooleanField()


class ErasureWriteSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ErasureRequestSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)

    class Meta:
        model = ErasureRequest
        fields = [
            "id", "patient_id", "state", "reason", "decision_note",
            "outcome_summary", "retained_until", "created_at", "decided_at",
            "executed_at",
        ]
        read_only_fields = fields
