"""Content inspection for untrusted report uploads (spec section 39).

The extension and the ``Content-Type`` header both come from the client, so
neither is evidence of anything. Renaming ``payload.exe`` to ``report.pdf`` and
declaring ``application/pdf`` satisfies both checks. This module looks at the
bytes instead.

What it is and is not: this is a **content-type and active-content gate**, not
an antivirus engine. It cannot recognise malware families. Its job is to make
sure a stored file really is the inert document type it claims to be, so that
whatever later opens it - a parser here, a clinician's PDF reader on a laptop -
is not handed something else entirely. Deploying a real scanner (ClamAV or a
managed service) alongside it is still worth doing; point
``REPORT_UPLOAD_SCANNER`` at a callable that chains both.
"""
from __future__ import annotations

import re

from django.core.files.uploadedfile import UploadedFile

from apps.common.errors import ValidationFailed

#: Leading bytes that identify each format we accept. A file must match the
#: signature for the extension it claims.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    # Little-endian and big-endian TIFF.
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
}

_CONTENT_TYPE_FOR: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

#: Executable and script formats, checked explicitly so the error can say what
#: was actually uploaded rather than "not a PDF".
_EXECUTABLE_SIGNATURES: list[tuple[bytes, str]] = [
    (b"MZ", "a Windows executable"),
    (b"\x7fELF", "a Linux executable"),
    (b"\xca\xfe\xba\xbe", "a Mach-O or Java class file"),
    (b"PK\x03\x04", "a zip archive (or an Office/OpenDocument file)"),
    (b"Rar!\x1a\x07", "a RAR archive"),
    (b"\x1f\x8b", "a gzip archive"),
    (b"#!", "a shell script"),
    (b"<?php", "a PHP script"),
    (b"<!DOCTYPE html", "an HTML document"),
    (b"<html", "an HTML document"),
]

#: The EICAR test string. Any scanner that cannot catch this is not running.
_EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR"

#: PDF constructs that make a document *do* something when opened. A laboratory
#: report has no legitimate need for any of them.
_PDF_ACTIVE_CONTENT: list[tuple[bytes, str]] = [
    (b"/JavaScript", "embedded JavaScript"),
    (b"/JS", "embedded JavaScript"),
    (b"/Launch", "a launch action (runs an external program)"),
    (b"/EmbeddedFile", "an embedded file attachment"),
    (b"/OpenAction", "an action that runs when the document is opened"),
    (b"/AA", "an automatic action trigger"),
    (b"/RichMedia", "embedded rich media"),
    (b"/XFA", "an XFA form"),
]

#: How much of the file to inspect for active content. Reading the whole thing
#: would mean holding 25 MiB per concurrent upload; the constructs above appear
#: in the catalogue and object headers, near the start, or in the trailer.
_INSPECT_BYTES = 2 * 1024 * 1024


def _read_head(uploaded_file: UploadedFile, size: int) -> bytes:
    uploaded_file.seek(0)
    head = uploaded_file.read(size)
    uploaded_file.seek(0)
    return head


def sniff_extension(head: bytes) -> str | None:
    """The extension the leading bytes actually correspond to, if any."""
    for ext, signatures in _MAGIC.items():
        if any(head.startswith(sig) for sig in signatures):
            return ext
    return None


def verify_declared_type(uploaded_file: UploadedFile, declared_ext: str) -> None:
    """The bytes must match the extension and content type the client claimed."""
    head = _read_head(uploaded_file, 4096)
    if not head:
        raise ValidationFailed("The uploaded file is empty.")

    expected = _MAGIC.get(declared_ext)
    if expected is None:
        raise ValidationFailed(f"File extension '{declared_ext}' is not permitted.")

    if any(head.startswith(sig) for sig in expected):
        return

    for signature, description in _EXECUTABLE_SIGNATURES:
        if head.startswith(signature):
            raise ValidationFailed(
                f"This file is {description}, not a {declared_ext.lstrip('.').upper()} "
                f"document. Please upload the report itself."
            )

    actual = sniff_extension(head)
    if actual:
        raise ValidationFailed(
            f"This file is really a {actual.lstrip('.').upper()} file but was "
            f"uploaded as {declared_ext.lstrip('.').upper()}. Please upload it "
            f"with the correct file type."
        )
    raise ValidationFailed(
        f"This does not look like a {declared_ext.lstrip('.').upper()} document. "
        f"The file may be damaged or incomplete - please try uploading it again."
    )


def scan(uploaded_file: UploadedFile) -> None:
    """The default ``REPORT_UPLOAD_SCANNER``. Raises on anything suspicious.

    Deliberately conservative: a report that is refused can be re-uploaded or
    handed to a person, whereas a hostile file that is accepted is stored,
    served back to clinicians, and fed to a parser.
    """
    import os

    name = uploaded_file.name or ""
    ext = os.path.splitext(name)[1].lower()

    verify_declared_type(uploaded_file, ext)

    body = _read_head(uploaded_file, _INSPECT_BYTES)

    if _EICAR in body:
        raise ValidationFailed(
            "This file was refused by the malware check. If you believe this is "
            "a mistake, please contact support."
        )

    if ext == ".pdf":
        for marker, description in _PDF_ACTIVE_CONTENT:
            if marker in body:
                raise ValidationFailed(
                    f"This PDF contains {description}, which is not allowed in an "
                    f"uploaded report. Please upload a plain PDF of the report, or "
                    f"a photo of it."
                )

    # A double extension is how a file gets past a human reading the filename.
    if re.search(r"\.(exe|bat|cmd|com|scr|js|vbs|ps1|sh|jar|msi|dll)\.", name, re.I):
        raise ValidationFailed(
            "This file name looks unsafe. Please rename the file and try again."
        )


def content_type_for(ext: str) -> str:
    """The content type we will serve this file back as, from its real type.

    Never echo the client's declared content type back in a download response:
    that is how a stored file becomes a stored XSS.
    """
    return _CONTENT_TYPE_FOR.get(ext, "application/octet-stream")
