"""Text extraction from an uploaded report file (spec section 12).

Django owns file storage, so text extraction happens here rather than in the
intelligence service. PDFs with an embedded text layer are read with
``pypdf``. Scanned images require a real OCR engine (integration point below);
without one, extraction returns empty and the pipeline routes the report to
human review rather than proceeding on a bad read.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("caresense.reports.ocr")

_PDF_TYPES = {"application/pdf"}
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff"}


def extract_text_from_report(report) -> str:
    content_type = (report.file_content_type or "").lower()
    name = (report.original_filename or "").lower()

    if content_type in _PDF_TYPES or name.endswith(".pdf"):
        return _pdf_text(report.source_file)
    if content_type in _IMAGE_TYPES or name.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
        return _image_ocr(report.source_file)
    return ""


def _pdf_text(file_field) -> str:
    try:
        from pypdf import PdfReader

        file_field.open("rb")
        reader = PdfReader(file_field)
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(pages).strip()
    except Exception as exc:  # noqa: BLE001 - a bad file must not crash the pipeline
        logger.warning("pdf_text_extraction_failed", extra={"error": str(exc)})
        return ""
    finally:
        try:
            file_field.close()
        except Exception:  # noqa: S110 - closing a handle must not mask the result
            pass


def _image_ocr(file_field) -> str:  # pragma: no cover - integration point
    """Wire a real OCR engine (e.g. Tesseract, a cloud OCR API) here. It must
    return plain text plus, ideally, per-block confidence. Until then, image
    reports are routed to human review."""
    logger.info("image_ocr_not_configured")
    return ""
