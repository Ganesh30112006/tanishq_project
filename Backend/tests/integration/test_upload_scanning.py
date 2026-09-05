"""Uploads are public, untrusted input. These are the ways in.

The extension and the Content-Type header are supplied by whoever is uploading,
so neither proves anything. Every test here sends a file whose declared type
passes the old checks and whose actual bytes are something else.
"""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.common.errors import ValidationFailed
from apps.reports.scanning import content_type_for, scan, sniff_extension

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _upload(name: str, body: bytes, content_type: str = "application/pdf"):
    return SimpleUploadedFile(name, body, content_type=content_type)


# --- files that are not what they say they are ---------------------------
def test_a_windows_executable_renamed_to_pdf_is_refused():
    """The whole point: extension and content type both say PDF."""
    payload = _upload("results.pdf", b"MZ\x90\x00" + b"\x00" * 128)
    with pytest.raises(ValidationFailed) as exc:
        scan(payload)
    assert "Windows executable" in str(exc.value)


def test_a_linux_executable_renamed_to_pdf_is_refused():
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("scan.pdf", b"\x7fELF\x02\x01\x01" + b"\x00" * 64))
    assert "Linux executable" in str(exc.value)


def test_a_zip_renamed_to_pdf_is_refused():
    """Covers Office documents and any archive smuggled in as a report."""
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("report.pdf", b"PK\x03\x04" + b"\x00" * 64))
    assert "zip archive" in str(exc.value)


def test_html_renamed_to_pdf_is_refused():
    """An HTML file served back to a browser is the stored-XSS route."""
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("report.pdf", b"<html><script>alert(1)</script></html>"))
    assert "HTML" in str(exc.value)


def test_a_png_uploaded_as_a_pdf_is_refused_with_the_real_type():
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("report.pdf", PNG_HEADER))
    assert "really a PNG" in str(exc.value)


def test_an_empty_file_is_refused():
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("report.pdf", b""))
    assert "empty" in str(exc.value).lower()


def test_a_shell_script_renamed_to_pdf_is_refused():
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("report.pdf", b"#!/bin/sh\nrm -rf /\n"))
    assert "shell script" in str(exc.value)


# --- the malware backstop -------------------------------------------------
def test_the_eicar_test_string_is_caught():
    """If this passes, no scanning is happening at all."""
    eicar = (
        b"%PDF-1.4\n"
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*\n"
    )
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("report.pdf", eicar))
    assert "malware" in str(exc.value).lower()


# --- PDFs that do something when opened ----------------------------------
@pytest.mark.parametrize(
    "marker,phrase",
    [
        (b"/JavaScript (app.alert\\(1\\))", "JavaScript"),
        (b"/Launch /F (cmd.exe)", "launch action"),
        (b"/OpenAction << /S /JavaScript >>", "JavaScript"),
        (b"/EmbeddedFile 12 0 R", "embedded file"),
    ],
)
def test_a_pdf_carrying_active_content_is_refused(marker, phrase):
    body = b"%PDF-1.4\n1 0 obj\n<< " + marker + b" >>\nendobj\n%%EOF\n"
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("report.pdf", body))
    assert phrase in str(exc.value)


def test_a_double_extension_filename_is_refused():
    with pytest.raises(ValidationFailed) as exc:
        scan(_upload("invoice.exe.pdf", MINIMAL_PDF))
    assert "unsafe" in str(exc.value).lower()


# --- real documents still get through ------------------------------------
def test_a_genuine_pdf_passes():
    scan(_upload("report.pdf", MINIMAL_PDF))


def test_a_genuine_png_passes():
    scan(_upload("scan.png", PNG_HEADER, content_type="image/png"))


def test_a_genuine_jpeg_passes():
    scan(_upload("photo.jpg", JPEG_HEADER, content_type="image/jpeg"))


def test_a_genuine_tiff_passes():
    for header in (b"II*\x00", b"MM\x00*"):
        scan(_upload("scan.tiff", header + b"\x00" * 64, content_type="image/tiff"))


def test_the_scanner_rewinds_so_the_file_can_still_be_stored():
    """A scanner that consumes the stream would store a zero-byte report."""
    handle = _upload("report.pdf", MINIMAL_PDF)
    scan(handle)
    assert handle.read() == MINIMAL_PDF


# --- what we serve back ---------------------------------------------------
def test_download_content_type_comes_from_the_extension_not_the_uploader():
    assert content_type_for(".pdf") == "application/pdf"
    assert content_type_for(".png") == "image/png"
    # Anything unrecognised must never become something a browser will render.
    assert content_type_for(".html") == "application/octet-stream"
    assert content_type_for("") == "application/octet-stream"


def test_sniffing_identifies_the_real_format():
    assert sniff_extension(MINIMAL_PDF) == ".pdf"
    assert sniff_extension(PNG_HEADER) == ".png"
    assert sniff_extension(b"MZ\x90\x00") is None


# --- and the whole intake path refuses it -------------------------------
@pytest.mark.django_db
def test_the_upload_endpoint_refuses_a_disguised_executable(make_patient, make_user):
    """End of the line: the service layer, not just the scanner in isolation."""
    from apps.common.enums import Role
    from apps.reports.services import ReportService

    patient = make_patient()
    uploader = make_user(Role.PATIENT)
    with pytest.raises(ValidationFailed):
        ReportService().register_upload(
            patient=patient,
            uploaded_file=_upload("results.pdf", b"MZ\x90\x00" + b"\x00" * 128),
            uploaded_by=uploader,
        )


@pytest.mark.django_db
def test_the_upload_endpoint_accepts_a_real_pdf(make_patient, make_user):
    from apps.common.enums import Role
    from apps.reports.models import Report
    from apps.reports.services import ReportService

    patient = make_patient()
    uploader = make_user(Role.PATIENT)
    report = ReportService().register_upload(
        patient=patient,
        uploaded_file=_upload("report.pdf", MINIMAL_PDF),
        uploaded_by=uploader,
    )
    assert Report.objects.filter(pk=report.pk).exists()
    assert report.file_size == len(MINIMAL_PDF)
