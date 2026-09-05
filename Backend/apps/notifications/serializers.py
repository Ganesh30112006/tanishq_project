from __future__ import annotations

from rest_framework import serializers

from apps.common.enums import MissingDataTaskStatus
from apps.notifications.models import MissingDataTask, Notification


class NotificationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "category",
            "subject",
            "body",
            "priority",
            "status",
            "related_resource_type",
            "related_resource_id",
            "created_at",
            "read_at",
        ]
        read_only_fields = fields


class MissingDataTaskSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)

    class Meta:
        model = MissingDataTask
        fields = [
            "id", "patient_id", "requested_data", "reason", "source_workflow",
            "priority", "assigned_role", "status", "lookup_state",
            "escalation_level", "sla_hours", "due_at", "last_escalated_at",
            "acknowledged_at", "resolved_at", "resolution_note", "created_at",
        ]
        read_only_fields = fields


class MissingDataTaskTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MissingDataTaskStatus.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)
