"""An OCR failure produces no clinical data - not a guess at it.

The whole point of adding OCR is that a photographed report currently yields
nothing. The danger in fixing that is the failure mode where a bad read yields
*something*: a half-recognised number, a wrong unit, a value with no reference
range, presented as though it were extracted cleanly.

These tests pin the safe behaviour of the current pipeline before the new OCR
module is built, so that the new module has to preserve it:

* no text  -> the report is held for review, and not one clinical row is written
* OCR raises -> the transaction rolls back, nothing is persisted, nothing finalises
* OCR returns noise -> no typed clinical value is manufactured from it
"""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.common.enums import ReportProcessingState, ValidationStatus
from apps.reports.models import Report, ReportTest
from apps.reports.pipeline import ReportPipeline
from apps.reports.services import ReportService

pytestmark = [pytest.mark.regression, pytest.mark.django_db]

#: A byte-valid PNG header so the upload scanner accepts the file; there is no
#: real image behind it, which is exactly the point - OCR has nothing to read.
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _upload_image(patient, uploader, *, name="scan.png"):
    handle = SimpleUploadedFile(name, _PNG, content_type="image/png")
    return ReportService().register_upload(
        patient=patient, uploaded_file=handle, uploaded_by=uploader,
    )


def _run(report):
    return ReportPipeline().run(Report.objects.get(pk=report.pk))


def test_an_image_with_no_ocr_configured_is_held_for_review_with_no_rows(
    make_patient, make_user
):
    patient = make_patient()
    report = _upload_image(patient, make_user())

    result = _run(report)
    report.refresh_from_db()

    assert result.failed and result.code == "REVIEW_REQUIRED"
    assert report.processing_state == ReportProcessingState.REVIEW_REQUIRED
    assert "unreadable" in report.review_reason.lower() or "unavailable" in report.review_reason.lower()
    assert ReportTest.objects.filter(report=report).count() == 0
    assert report.validation_status != ValidationStatus.PASSED


def test_an_ocr_engine_that_raises_persists_nothing(make_patient, make_user, monkeypatch):
    """A crash mid-extraction must not leave a half-built report behind."""
    patient = make_patient()
    report = _upload_image(patient, make_user())

    def boom(_report):
        raise RuntimeError("OCR backend unavailable")

    monkeypatch.setattr("apps.reports.ocr.extract_text_from_report", boom)

    with pytest.raises(RuntimeError):
        _run(report)

    report.refresh_from_db()
    # run() is atomic: the raise rolls the whole attempt back.
    assert report.processing_state != ReportProcessingState.FINALIZED
    assert ReportTest.objects.filter(report=report).count() == 0
    assert not report.extracted_text.strip()


def test_ocr_noise_does_not_become_a_typed_clinical_value(
    make_patient, make_user, monkeypatch
):
    """Text that is not a lab line must not yield a normalised number + unit."""
    patient = make_patient()
    report = _upload_image(patient, make_user())

    noise = "Page 3 of 12\n~~~~ scanned copy ~~~~\nHb â€” g/dL\n|||| 9.2 ||||\n"
    monkeypatch.setattr(
        "apps.reports.ocr.extract_text_from_report", lambda _r: noise
    )

    _run(report)
    report.refresh_from_db()

    assert report.processing_state != ReportProcessingState.FINALIZED
    # If anything was materialised at all, it is not a clean, validated value.
    for test in ReportTest.objects.filter(report=report):
        assert not (
            test.value_normalized is not None
            and test.unit_normalized
            and test.validation_status == ValidationStatus.PASSED
        ), f"noise produced a validated clinical value: {test.name} {test.value_normalized}"


def test_a_pdf_with_no_text_layer_is_also_held_not_guessed(make_patient, make_user):
    """The pre-existing safe path for scanned PDFs, pinned so it stays."""
    patient = make_patient()
    handle = SimpleUploadedFile("scanned.pdf", b"%PDF-1.4\n%%EOF\n",
                                content_type="application/pdf")
    report = ReportService().register_upload(
        patient=patient, uploaded_file=handle, uploaded_by=make_user(),
    )

    result = _run(report)
    report.refresh_from_db()

    assert result.failed
    assert report.processing_state == ReportProcessingState.REVIEW_REQUIRED
    assert ReportTest.objects.filter(report=report).count() == 0
