"""Real PDF text extraction in the report pipeline (spec section 12)."""
from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.common.enums import ReportClass, ReportProcessingState
from apps.reports.models import Report, ReportTest
from apps.reports.pipeline import ReportPipeline
from apps.reports.services import ReportService

pytestmark = pytest.mark.django_db


def _pdf_bytes(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def test_pipeline_extracts_text_from_a_real_pdf(make_patient, make_user):
    pdf = _pdf_bytes(
        ["CHEMISTRY", "Collected: 2024-05-01 09:00", "Reported: 2024-05-01 15:00", "Glucose: 5.4 mmol/L"]
    )
    upload = SimpleUploadedFile("glucose.pdf", pdf, content_type="application/pdf")
    report = ReportService().register_upload(
        patient=make_patient(), uploaded_file=upload, uploaded_by=make_user(),
        class_hint=ReportClass.GLUCOSE,
    )
    assert report.extracted_text == ""  # not supplied; OCR happens in the pipeline

    ReportPipeline().run(Report.objects.get(pk=report.pk))
    report.refresh_from_db()

    assert "Glucose" in report.extracted_text
    assert report.processing_state == ReportProcessingState.FINALIZED
    test = ReportTest.objects.get(report=report, name="glucose")
    assert float(test.value_normalized) == 5.4


def test_unreadable_pdf_is_routed_to_review(make_patient, make_user):
    upload = SimpleUploadedFile("junk.pdf", b"%PDF-1.4 not really a pdf", content_type="application/pdf")
    report = ReportService().register_upload(
        patient=make_patient(), uploaded_file=upload, uploaded_by=make_user(),
        class_hint=ReportClass.GLUCOSE,
    )
    ReportPipeline().run(Report.objects.get(pk=report.pk))
    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.REVIEW_REQUIRED
    assert "unreadable" in report.review_reason.lower()
