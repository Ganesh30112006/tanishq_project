from __future__ import annotations

from rest_framework import serializers

from apps.ai.models import AiInteraction, AiKnowledgeDocument


class AiAskSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=AiInteraction.Kind.choices)
    question = serializers.CharField(max_length=2000)
    report_id = serializers.UUIDField(required=False)


class AiInteractionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True, allow_null=True)

    class Meta:
        model = AiInteraction
        fields = [
            "id",
            "patient_id",
            "kind",
            "status",
            "prompt_summary",
            "output_text",
            "output_flags",
            "context_refs",
            "model_name",
            "correlation_id",
            "created_at",
        ]
        read_only_fields = fields


class AiKnowledgeDocumentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = AiKnowledgeDocument
        fields = ["id", "title", "category", "body", "source", "version"]
        read_only_fields = fields
