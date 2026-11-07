"""A ``REPORT_UPLOAD_SCANNER`` backed by ClamAV's daemon (clamd).

Set ``REPORT_UPLOAD_SCANNER=apps.reports.clamav:scan`` and point it at clamd:
``CLAMD_SOCKET`` for its local socket (Ubuntu's clamav-daemon listens on
``/var/run/clamav/clamd.ctl`` out of the box), or ``CLAMD_HOST`` /
``CLAMD_PORT`` for TCP. The file is streamed with clamd's INSTREAM command, so
no shared disk is needed and no Python package is added.

**It fails closed.** If clamd cannot be reached, or answers anything but a
clean result, the upload is refused. A report that is refused can be uploaded
again in a minute; a file that was never checked is stored, served back and
fed to a parser.
"""
from __future__ import annotations

import os
import socket
import struct

from django.core.files.uploadedfile import UploadedFile

from apps.common.errors import ValidationFailed

_CHUNK = 64 * 1024

_UNAVAILABLE = (
    "We could not check this file for viruses right now, so it has not been "
    "saved. Please try again in a few minutes."
)
_INFECTED = (
    "This file was refused by the virus check. If you believe this is a "
    "mistake, please contact support."
)


def _connect() -> socket.socket:
    path = os.environ.get("CLAMD_SOCKET", "")
    if path:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(30)
        try:
            conn.connect(path)
        except OSError:
            conn.close()
            raise
        return conn
    address = os.environ.get("CLAMD_HOST", "127.0.0.1"), int(os.environ.get("CLAMD_PORT", "3310"))
    return socket.create_connection(address, timeout=30)


def scan(uploaded_file: UploadedFile) -> None:
    uploaded_file.seek(0)
    try:
        with _connect() as conn:
            conn.sendall(b"zINSTREAM\0")
            for chunk in uploaded_file.chunks(_CHUNK):
                conn.sendall(struct.pack("!L", len(chunk)) + chunk)
            conn.sendall(struct.pack("!L", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                part = conn.recv(4096)
                if not part:
                    break
                reply += part
    except OSError as exc:
        raise ValidationFailed(_UNAVAILABLE) from exc
    finally:
        uploaded_file.seek(0)

    answer = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
    if answer.endswith("FOUND"):
        raise ValidationFailed(_INFECTED)
    if answer != "stream: OK":
        # ERROR, a size-limit refusal, or something unrecognised: not clean.
        raise ValidationFailed(_UNAVAILABLE)
