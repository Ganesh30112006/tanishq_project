"""The same PDF builder the document tests use.

The extraction benchmark's adapter has to be exercised against a real
``DocumentResult``, not a hand-built one: the whole point of keeping the
adapter beside the corpus loader is that a drift between what an annotator
records and what the pipeline produces shows up.
"""
from __future__ import annotations

import io

import pytest


@pytest.fixture
def text_pdf():
    """A real single-page PDF whose text layer contains the given lines."""

    def _build(lines: list[str]) -> bytes:
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=(400, 400))
        y = 360
        for line in lines:
            c.drawString(30, y, line)
            y -= 16
        c.showPage()
        c.save()
        return buffer.getvalue()

    return _build
