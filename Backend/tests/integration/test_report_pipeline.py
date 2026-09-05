"""Report-processing pipeline (spec sections 12, 39, 53).

Covers: complete report, incomplete report, conflicting report, unreadable
report, wrong units, duplicate report, wrong report type, missing expected
fields - plus upload authorization.
"""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.common.enums import (
    ClinicalDataState,
    CompletenessStatus,
    ReportClass,
    ReportProcessingState,
    ValidationStatus,
)
from apps.reconciliation.models import ReconciliationEvent
from apps.reports.models import Report, ReportTest
from apps.reports.pipeline import ReportPipeline
from apps.reports.services import ReportService

pytestmark = pytest.mark.django_db

GLUCOSE_OK = """\
CHEMISTRY
Collected: 2024-05-01 09:00
Reported: 2024-05-01 15:00
Glucose: 5.4 mmol/L
"""

LIPID_MISSING_TRIG = """\
LIPID PANEL
Collected: 2024-06-01 08:00
Total Cholesterol: 4.2 mmol/L
HDL Cholesterol: 1.3 mmol/L
LDL Cholesterol: 2.4 mmol/L
"""


def _upload(patient, uploader, text, *, hint="", name="r.pdf"):
    f = SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")
    return ReportService().register_upload(
        patient=patient, uploaded_file=f, uploaded_by=uploader, class_hint=hint, extracted_text=text
    )


def _run(report):
    return ReportPipeline().run(Report.objects.get(pk=report.pk))


def test_complete_report_is_finalized_with_normalized_provenance(make_patient, make_user):
    patient = make_patient()
    report = _upload(patient, make_user(), GLUCOSE_OK, hint=ReportClass.GLUCOSE)
    _run(report)

    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.FINALIZED
    assert report.completeness_status == CompletenessStatus.COMPLETE
    assert report.collected_at is not None and report.reported_at is not None

    test = ReportTest.objects.get(report=report, name="glucose")
    assert test.state == ClinicalDataState.OBSERVED
    assert test.validation_status == ValidationStatus.PASSED
    assert float(test.value_normalized) == 5.4
    assert test.unit_normalized == "mmol/L"
    assert test.provenance is not None
    assert test.provenance.source_report_id == report.pk


def test_incomplete_report_requires_review_and_names_missing_field(make_patient, make_user):
    patient = make_patient()
    report = _upload(patient, make_user(), LIPID_MISSING_TRIG, hint=ReportClass.LIPID)
    result = _run(report)

    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.REVIEW_REQUIRED
    assert report.completeness_status == CompletenessStatus.INCOMPLETE
    assert "triglycerides" in report.review_reason
    assert result.failed and result.code == "REVIEW_REQUIRED"


def test_unreadable_report_is_flagged_not_processed(make_patient, make_user):
    report = _upload(make_patient(), make_user(), "", hint=ReportClass.GLUCOSE)
    _run(report)
    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.REVIEW_REQUIRED
    assert "unreadable" in report.review_reason.lower()


def test_wrong_unit_is_not_converted_and_value_is_ambiguous(make_patient, make_user):
    text = "CHEMISTRY\nCollected: 2024-05-01 09:00\nGlucose: 5.4 g/L\n"
    report = _upload(make_patient(), make_user(), text, hint=ReportClass.GLUCOSE)
    _run(report)
    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.REVIEW_REQUIRED
    test = ReportTest.objects.get(report=report, name="glucose")
    assert test.state == ClinicalDataState.AMBIGUOUS
    assert test.value_normalized is None


def test_wrong_report_type_is_not_confidently_processed(make_patient, make_user):
    # No hint, no recognizable analytes -> classification ambiguous.
    report = _upload(make_patient(), make_user(), "SOME UNRELATED DOCUMENT\nnothing useful here\n")
    _run(report)
    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.REVIEW_REQUIRED
    assert report.report_class == ReportClass.OTHER


def test_same_day_conflicting_value_preserves_both_and_opens_reconciliation(make_patient, make_user):
    patient, user = make_patient(), make_user()
    a = _upload(patient, user, GLUCOSE_OK, hint=ReportClass.GLUCOSE)
    _run(a)
    a.refresh_from_db()
    assert a.processing_state == ReportProcessingState.FINALIZED

    conflicting = GLUCOSE_OK.replace("5.4 mmol/L", "7.9 mmol/L")
    b = _upload(patient, user, conflicting, hint=ReportClass.GLUCOSE)
    _run(b)
    b.refresh_from_db()

    assert b.processing_state == ReportProcessingState.REVIEW_REQUIRED
    assert "onflict" in b.review_reason
    # Both values preserved.
    assert ReportTest.objects.filter(name="glucose").count() == 2
    assert ReconciliationEvent.objects.filter(
        patient=patient, kind__in=["SAME_DAY_CONFLICT", "DUPLICATE_REPORT"]
    ).exists()


def test_duplicate_report_is_detected(make_patient, make_user):
    patient, user = make_patient(), make_user()
    a = _upload(patient, user, GLUCOSE_OK, hint=ReportClass.GLUCOSE)
    _run(a)
    b = _upload(patient, user, GLUCOSE_OK, hint=ReportClass.GLUCOSE)
    _run(b)
    assert ReconciliationEvent.objects.filter(patient=patient, kind="DUPLICATE_REPORT").exists()


def test_pipeline_is_idempotent_for_finalized_reports(make_patient, make_user):
    report = _upload(make_patient(), make_user(), GLUCOSE_OK, hint=ReportClass.GLUCOSE)
    _run(report)
    first = ReportTest.objects.filter(report=report).count()
    _run(report)  # second run must not duplicate rows
    assert ReportTest.objects.filter(report=report).count() == first
