from __future__ import annotations

from rest_framework import serializers

from apps.common.enums import ReportClass
from apps.reports.models import (
    Report,
    ReportAnalysis,
    ReportFinding,
    ReportSection,
    ReportTest,
)


class ReportTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportTest
        fields = [
            "name",
            "loinc_code",
            "value_raw",
            "unit_raw",
            "value_normalized",
            "unit_normalized",
            "conversion_rule_version",
            "reference_range",
            "abnormal_flag",
            "method",
            "state",
            "validation_status",
            "ocr_confidence",
            "entity_confidence",
            "context_confidence",
            "observed_at",
        ]
        read_only_fields = fields


class ReportSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportSection
        fields = ["name", "ordinal", "detection_confidence"]
        read_only_fields = fields


class ReportFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportFinding
        fields = ["category", "text", "confidence"]
        read_only_fields = fields


class ReportSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    uploaded_by = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    tests = ReportTestSerializer(many=True, read_only=True)
    sections = ReportSectionSerializer(many=True, read_only=True)
    findings = ReportFindingSerializer(many=True, read_only=True)

    class Meta:
        model = Report
        fields = [
            "id",
            "patient_id",
            "patient_name",
            "title",
            "uploaded_by",
            "report_class",
            "class_hint",
            "classification_confidence",
            "processing_state",
            "completeness_status",
            "validation_status",
            "review_reason",
            "facility",
            "ordering_provider",
            "specimen",
            "collected_at",
            "reported_at",
            "original_filename",
            "file_sha256",
            "file_size",
            "created_at",
            "sections",
            "tests",
            "findings",
        ]
        read_only_fields = fields

    def get_uploaded_by(self, obj: Report) -> str | None:
        if obj.uploaded_by_id is None:
            return None
        return obj.uploaded_by.full_name or obj.uploaded_by.email

    def get_title(self, obj: Report) -> str:
        if obj.original_filename:
            return obj.original_filename
        label = obj.get_report_class_display() if obj.report_class else "Unclassified"
        return f"{label} report"


class ReportUploadSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    file = serializers.FileField()
    class_hint = serializers.ChoiceField(choices=ReportClass.choices, required=False, allow_blank=True)
    # Optional: text already obtained from OCR (or supplied directly in tests /
    # for plain-text reports). The client never supplies structured values.
    extracted_text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)


class ReportAnalysisSerializer(serializers.ModelSerializer):
    """The AI's analysis as the patient sees it. AI output, not a record."""

    report_id = serializers.UUIDField(source="report.public_id", read_only=True)
    analysed_at = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = ReportAnalysis
        fields = [
            "report_id", "status", "reason_code", "reason", "urgent", "values",
            "findings", "unusable", "text_source", "knowledge_version",
            "range_table_version", "detectors_run", "policy_version", "analysed_at",
        ]
        read_only_fields = fields
