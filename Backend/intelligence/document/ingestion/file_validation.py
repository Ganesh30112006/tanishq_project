"""Decide what a file actually is from its leading bytes.

The extension and the ``Content-Type`` header are both supplied by whoever
uploaded the file, so neither is evidence. This mirrors the signature checks in
``apps.reports.scanning`` deliberately: the two must agree on what counts as a
PDF or an image, or a file could pass one gate and fail the other.

This is a type gate, not a malware scanner. Active-content inspection for PDFs
stays in ``apps.reports.scanning``, which runs before anything reaches here.
"""
from __future__ import annotations

from intelligence.document.contracts import DocumentMediaType, FileValidation

#: Leading bytes that identify each accepted format.
_MAGIC: list[tuple[bytes, DocumentMediaType]] = [
    (b"%PDF-", DocumentMediaType.PDF),
    (b"\x89PNG\r\n\x1a\n", DocumentMediaType.PNG),
    (b"\xff\xd8\xff", DocumentMediaType.JPEG),
    (b"II*\x00", DocumentMediaType.TIFF),
    (b"MM\x00*", DocumentMediaType.TIFF),
]

#: Formats that must never be stored as a report, matched so the message can
#: say what was really uploaded.
_EXECUTABLE: list[tuple[bytes, str]] = [
    (b"MZ", "a Windows executable"),
    (b"\x7fELF", "a Linux executable"),
    (b"PK\x03\x04", "a zip or Office/OpenDocument file"),
    (b"\x1f\x8b", "a gzip archive"),
    (b"#!", "a shell script"),
    (b"<!DOCTYPE html", "an HTML document"),
    (b"<html", "an HTML document"),
]

_DECLARED_ALIASES = {
    "image/jpg": DocumentMediaType.JPEG,
    "image/pjpeg": DocumentMediaType.JPEG,
    "image/x-png": DocumentMediaType.PNG,
}


def _sniff(data: bytes) -> DocumentMediaType:
    for signature, media_type in _MAGIC:
        if data.startswith(signature):
            return media_type
    return DocumentMediaType.UNKNOWN


def validate_file(
    data: bytes,
    *,
    declared_type: str = "",
    max_bytes: int = 25 * 1024 * 1024,
) -> FileValidation:
    problems: list[str] = []
    size = len(data)

    if size == 0:
        return FileValidation(
            media_type=DocumentMediaType.UNKNOWN, declared_type=declared_type,
            size_bytes=0, ok=False, problems=["the file is empty"],
        )
    if size > max_bytes:
        problems.append(f"the file is {size} bytes, over the {max_bytes} limit")

    for signature, label in _EXECUTABLE:
        if data.startswith(signature):
            return FileValidation(
                media_type=DocumentMediaType.UNKNOWN, declared_type=declared_type,
                size_bytes=size, ok=False,
                problems=[f"the file is {label}, not a medical report"],
            )

    media_type = _sniff(data)
    if media_type is DocumentMediaType.UNKNOWN:
        problems.append(
            "the leading bytes do not match a PDF, PNG, JPEG or TIFF"
        )

    declared = (declared_type or "").lower().strip()
    if declared and media_type is not DocumentMediaType.UNKNOWN:
        resolved = _DECLARED_ALIASES.get(declared)
        try:
            resolved = resolved or DocumentMediaType(declared)
        except ValueError:
            resolved = None
        if resolved is not None and resolved is not media_type:
            problems.append(
                f"declared as {declared} but the bytes are {media_type.value}"
            )

    return FileValidation(
        media_type=media_type, declared_type=declared_type, size_bytes=size,
        ok=not problems, problems=problems,
    )
