from __future__ import annotations

from rest_framework import serializers

from apps.reconciliation.models import ReconciliationEvent, ReconciliationItem


class ReconciliationItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReconciliationItem
        fields = ["resource_type", "resource_id", "role_in_conflict", "snapshot"]
        read_only_fields = fields


class ReconciliationEventSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True, allow_null=True)
    items = ReconciliationItemSerializer(many=True, read_only=True)

    class Meta:
        model = ReconciliationEvent
        fields = [
            "id", "patient_id", "kind", "status", "summary",
            "detected_at", "detected_by_workflow", "resolved_at", "resolution", "items",
        ]
        read_only_fields = fields


class ReconciliationResolveSerializer(serializers.Serializer):
    resolution = serializers.CharField(max_length=255)
