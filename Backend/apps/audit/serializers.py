from __future__ import annotations

from rest_framework import serializers

from apps.audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "actor_label",
            "actor_roles",
            "action",
            "resource_type",
            "resource_id",
            "result",
            "reason",
            "request_id",
            "client_ip",
            "metadata",
        ]
        read_only_fields = fields
