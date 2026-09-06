"""Stage 1-2: is this the document it claims to be, and can its text be read?

``file_validation`` looks at the bytes, not the filename or the declared
content type, both of which come from the uploader. ``text_layer`` decides
whether a PDF carries enough embedded text to skip OCR entirely; an image, or
a PDF that is really a scan, falls through to the OCR stage.
"""
from __future__ import annotations

from intelligence.document.ingestion.file_validation import validate_file
from intelligence.document.ingestion.text_layer import extract_text_layer

__all__ = ["validate_file", "extract_text_layer"]
