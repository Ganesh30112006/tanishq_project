from __future__ import annotations

from rest_framework import serializers

from apps.common.enums import Role


class MetricSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.CharField()
    context = serializers.CharField()
    tone = serializers.ChoiceField(choices=["neutral", "positive", "warning", "critical"])


class ActivityItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    detail = serializers.CharField()
    timestamp = serializers.DateTimeField()
    type = serializers.ChoiceField(choices=["risk", "report", "note", "measurement", "alert"])


class DashboardSummarySerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)
    greeting = serializers.CharField()
    metrics = MetricSerializer(many=True)
    recent_activity = ActivityItemSerializer(many=True)
