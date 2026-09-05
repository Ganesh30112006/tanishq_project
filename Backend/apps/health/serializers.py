from __future__ import annotations

from rest_framework import serializers

from apps.common.enums import ClinicalDataState
from apps.health.models import HealthMeasurement, MeasurementKind


class HealthMeasurementSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)

    class Meta:
        model = HealthMeasurement
        fields = [
            "id", "patient_id", "kind", "value_num", "unit", "state",
            "observed_at", "recorded_at", "source",
        ]
        read_only_fields = ["id", "patient_id", "recorded_at"]


class HealthMeasurementWriteSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=MeasurementKind.choices)
    state = serializers.ChoiceField(choices=ClinicalDataState.choices)
    observed_at = serializers.DateTimeField()
    value = serializers.DecimalField(
        max_digits=12, decimal_places=4, required=False, allow_null=True
    )
    unit = serializers.CharField(max_length=20, required=False, allow_blank=True)
    source = serializers.CharField(max_length=60, required=False, allow_blank=True)
