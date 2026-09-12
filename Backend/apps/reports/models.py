"""Report intelligence data model.

A medical report is structured knowledge, not just a file (spec section 11).
Extracted values keep their raw form, normalized form, per-stage confidence
and validation status. An LLM never writes a trusted value directly - see
:mod:`apps.reports.services` (spec section 12).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import (
    ClinicalDataState,
    CompletenessStatus,
    ExtractionMethod,
    ReportClass,
    ReportProcessingState,
    ValidationStatus,
)
from apps.common.models import UUIDTimeStampedModel, VersionedModel
from apps.patients.models import Patient


class ReportSchema(UUIDTimeStampedModel):
    """Versioned, configurable expected-schema for a report type (sections 14, 15)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    report_class = models.CharField(max_length=20, choices=ReportClass.choices)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    # definition: {expected_fields, required_fields, optional_fields, aliases,
    #              accepted_units, validation_rules, expected_sections,
    #              temporal_requirements}
    definition = models.JSONField(default=dict)

    class Meta:
        db_table = "reports_schema"
        constraints = [
            models.UniqueConstraint(
                fields=["report_class", "version"], name="uq_report_schema_version"
            )
        ]

    def __str__(self) -> str:
        return f"{self.report_class} v{self.version} ({self.status})"


class Report(VersionedModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="reports")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uploaded_reports"
    )

    report_class = models.CharField(max_length=20, choices=ReportClass.choices, blank=True)
    classification_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    schema = models.ForeignKey(
        ReportSchema, on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )

    processing_state = models.CharField(
        max_length=20, choices=ReportProcessingState.choices, default=ReportProcessingState.RECEIVED
    )
    completeness_status = models.CharField(
        max_length=12, choices=CompletenessStatus.choices, blank=True
    )
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.PENDING
    )
    review_reason = models.CharField(max_length=255, blank=True)

    facility = models.CharField(max_length=200, blank=True)
    ordering_provider = models.CharField(max_length=200, blank=True)
    specimen = models.CharField(max_length=120, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    reported_at = models.DateTimeField(null=True, blank=True)

    # Untrusted upload; stored privately, referenced by hash (spec section 39).
    source_file = models.FileField(upload_to="reports/%Y/%m/", max_length=255)
    original_filename = models.CharField(max_length=255, blank=True)
    file_sha256 = models.CharField(max_length=64, db_index=True)
    file_content_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)

    # Text obtained from OCR / a text upload. Populated by the pipeline, not the
    # client. Structured values are derived from this, never trusted from an LLM
    # without deterministic validation (spec section 12).
    extracted_text = models.TextField(blank=True)
    class_hint = models.CharField(
        max_length=20, choices=ReportClass.choices, blank=True,
        help_text="Report type asserted by the uploader; verified against the schema",
    )

    class Meta:
        db_table = "reports_report"
        indexes = [
            models.Index(fields=["patient", "report_class", "reported_at"]),
            models.Index(fields=["processing_state"]),
        ]

    def __str__(self) -> str:
        return f"Report {self.public_id} ({self.report_class or 'unclassified'})"


class ReportSection(UUIDTimeStampedModel):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=120)
    ordinal = models.PositiveIntegerField(default=0)
    raw_text = models.TextField(blank=True)
    detection_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )

    class Meta:
        db_table = "reports_section"
        ordering = ["ordinal"]


class ReportTest(UUIDTimeStampedModel):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="tests")
    section = models.ForeignKey(
        ReportSection, on_delete=models.SET_NULL, null=True, blank=True, related_name="tests"
    )
    name = models.CharField(max_length=120)
    loinc_code = models.CharField(max_length=20, blank=True)

    value_raw = models.CharField(max_length=120, blank=True)
    unit_raw = models.CharField(max_length=32, blank=True)
    value_normalized = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    unit_normalized = models.CharField(max_length=32, blank=True)
    conversion_rule_version = models.CharField(max_length=32, blank=True)
    reference_range = models.CharField(max_length=64, blank=True)
    abnormal_flag = models.CharField(max_length=8, blank=True)
    method = models.CharField(max_length=64, blank=True)

    state = models.CharField(
        max_length=16, choices=ClinicalDataState.choices, default=ClinicalDataState.PENDING
    )
    extraction_method = models.CharField(max_length=20, choices=ExtractionMethod.choices)
    ocr_confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    entity_confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    context_confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.PENDING
    )

    observed_at = models.DateTimeField(null=True, blank=True)
    provenance = models.ForeignKey(
        "medical_records.Provenance", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "reports_test"
        indexes = [models.Index(fields=["report", "name"])]


class ReportFinding(UUIDTimeStampedModel):
    class Category(models.TextChoices):
        FINDING = "FINDING", "Finding"
        INTERPRETATION = "INTERPRETATION", "Interpretation"
        CONCLUSION = "CONCLUSION", "Conclusion"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="findings")
    category = models.CharField(max_length=16, choices=Category.choices)
    text = models.TextField()
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    provenance = models.ForeignKey(
        "medical_records.Provenance", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "reports_finding"


class ReaderComparison(UUIDTimeStampedModel):
    """One report read twice: by the pipeline, and by the document service.

    This is the shadow dataset. It exists to answer a question that cannot be
    answered by turning the second reader on and watching: *where do the two
    readers actually disagree, and which of them is right?* Agreement alone
    says nothing - two readers can agree and both be wrong - so what is kept
    here is the disagreements, one row each, with the text that produced them.

    **Nothing here is a clinical record.** No row in this table is read by any
    clinical code path, appears in any patient-facing response, or feeds any
    detector. It is evidence about the software, held for the people deciding
    whether the second reader may be trusted with a clinical outcome.

    It inherits the report's lifecycle: the rows cascade with the report, and
    the excerpts are of text already retained in ``Report.extracted_text``, so
    this table adds no data that outlives the document it came from.
    """

    report = models.ForeignKey(
        Report, on_delete=models.CASCADE, related_name="reader_comparisons"
    )
    #: The mode in force when the comparison was made. Recorded because an
    #: advisory-mode comparison may have changed the outcome and a shadow one
    #: never did, and the two must not be pooled when the record is analysed.
    mode = models.CharField(max_length=12)

    #: What the existing pipeline decided, before any second opinion.
    existing_outcome = models.CharField(max_length=20)
    #: What the service said, or "" when it had no opinion.
    second_disposition = models.CharField(max_length=20, blank=True)
    second_available = models.BooleanField(default=False)
    unavailable_reason = models.CharField(max_length=200, blank=True)

    #: What kind of document this was. Recorded because the pilot's purpose
    #: is to find failure modes across the reports that actually arrive, and
    #: "have we seen a scan yet?" is otherwise unanswerable from this table -
    #: a record made entirely of clean PDFs looks complete and is not.
    report_class = models.CharField(max_length=20, blank=True)
    #: How the text was obtained, as the service reported it: an embedded PDF
    #: text layer, or OCR. The single strongest predictor of where the two
    #: readers will differ.
    text_source = models.CharField(max_length=32, blank=True)

    existing_value_count = models.PositiveIntegerField(default=0)
    second_value_count = models.PositiveIntegerField(default=0)
    #: True when the readers produced the same values and the same routing.
    #: Kept for filtering, never as a score on its own.
    agreed = models.BooleanField(default=False)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "reports_reader_comparison"
        indexes = [
            models.Index(fields=["mode", "agreed"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["report_class", "text_source"]),
        ]

    def __str__(self) -> str:
        return f"Reader comparison for {self.report.public_id} ({self.mode})"


class ReaderDisagreement(UUIDTimeStampedModel):
    """One place the two readers differed, kept with the text that caused it.

    The ``classification`` is the taxonomy the disagreement record exists to
    populate. Most of it cannot be decided from the two outputs - saying which
    reader was wrong means looking at the document - so the machine fills in
    only the classes that are observable from the responses themselves and
    leaves the rest ``UNKNOWN`` for a person. A classification nobody made is
    not a classification.
    """

    class Kind(models.TextChoices):
        """What was observed. Assigned by comparing the two outputs."""

        ONLY_EXISTING = "ONLY_EXISTING", "Only the existing reader produced a value"
        ONLY_SECOND = "ONLY_SECOND", "Only the second reader produced a value"
        VALUE_DIFFERS = "VALUE_DIFFERS", "Both produced a value and they differ"
        UNIT_DIFFERS = "UNIT_DIFFERS", "Same number, different unit"
        NOT_PERSISTABLE = "NOT_PERSISTABLE", "Second reader would not stand behind it"
        DOCUMENT_UNREADABLE = "DOCUMENT_UNREADABLE", "Second reader could not read the document"
        ROUTING_DIFFERS = "ROUTING_DIFFERS", "The readers would route the report differently"

    class Classification(models.TextChoices):
        """Why they differed. Decided by a person, except where noted."""

        SAFE_IMPROVEMENT = "SAFE_IMPROVEMENT", "The second reader was right"
        SAFE_ABSTENTION = "SAFE_ABSTENTION", "The second reader declined to guess"
        PARSER_ERROR = "PARSER_ERROR", "The second reader misread the line"
        NORMALIZATION_ERROR = "NORMALIZATION_ERROR", "The unit conversion was wrong"
        REFERENCE_RANGE_DIFFERENCE = (
            "REFERENCE_RANGE_DIFFERENCE", "The readers used different reference intervals"
        )
        CONFLICT_DETECTION = "CONFLICT_DETECTION", "The second reader found a real contradiction"
        OCR_FAILURE = "OCR_FAILURE", "The text could not be recovered"
        OLD_READER_ERROR = "OLD_READER_ERROR", "The existing pipeline was wrong"
        UNKNOWN = "UNKNOWN", "Not yet classified"

    comparison = models.ForeignKey(
        ReaderComparison, on_delete=models.CASCADE, related_name="disagreements"
    )
    analyte = models.CharField(max_length=120, blank=True)
    kind = models.CharField(max_length=24, choices=Kind.choices)

    existing_value = models.CharField(max_length=64, blank=True)
    existing_unit = models.CharField(max_length=32, blank=True)
    existing_state = models.CharField(max_length=16, blank=True)

    second_value = models.CharField(max_length=64, blank=True)
    second_unit = models.CharField(max_length=32, blank=True)
    second_status = models.CharField(max_length=16, blank=True)
    second_reason = models.CharField(max_length=120, blank=True)
    second_persistable = models.BooleanField(default=False)

    #: The printed label and the line it came from. Without these the record
    #: is a count, and a count cannot be adjudicated.
    printed_label = models.CharField(max_length=200, blank=True)
    excerpt = models.CharField(max_length=300, blank=True)

    classification = models.CharField(
        max_length=28, choices=Classification.choices, default=Classification.UNKNOWN
    )
    #: Who decided. "observed" where the class follows from the responses
    #: alone; otherwise the reviewer. Empty while unclassified.
    classified_by = models.CharField(max_length=120, blank=True)
    #: The version of the class definitions in force when the ruling was made.
    #: A ruling is an answer to a question, and if the question is later
    #: reworded the old answers are not silently re-interpreted as answers to
    #: the new one. Empty while unclassified.
    taxonomy_version = models.CharField(max_length=40, blank=True)
    classified_at = models.DateTimeField(null=True, blank=True)
    classification_note = models.TextField(blank=True)

    class Meta:
        db_table = "reports_reader_disagreement"
        indexes = [
            models.Index(fields=["classification"]),
            models.Index(fields=["kind"]),
            models.Index(fields=["analyte"]),
        ]

    def __str__(self) -> str:
        return f"{self.analyte or '?'}: {self.kind}"

    @property
    def is_unsafe(self) -> bool:
        """Both readers produced a number they stand behind, and they differ.

        The dangerous class: one of the two is a wrong clinical value carried
        with full confidence, and nothing in the outputs says which.
        """
        return (
            self.kind in (self.Kind.VALUE_DIFFERS, self.Kind.UNIT_DIFFERS)
            and self.second_persistable
        )
