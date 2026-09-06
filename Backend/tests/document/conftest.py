"""Shared builders for document-intelligence tests."""
from __future__ import annotations

import io

import pytest


def _pdf(lines: list[str] | None) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(400, 400))
    y = 360
    for line in lines or []:
        c.drawString(30, y, line)
        y -= 16
    c.showPage()
    c.save()
    return buffer.getvalue()


@pytest.fixture
def text_pdf():
    """A real single-page PDF whose text layer contains the given lines."""
    return lambda lines: _pdf(lines)


@pytest.fixture
def blank_pdf():
    """A valid PDF with no text at all - the 'scanned page' stand-in."""
    return _pdf(None)
