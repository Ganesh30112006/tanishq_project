"""The ClamAV adapter passes only a clean answer, and refuses when clamd is gone."""
from __future__ import annotations

import socket
import struct
import threading

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.common.errors import ValidationFailed
from apps.reports import clamav


def _fake_clamd(reply: bytes):
    """A one-shot clamd that reads one INSTREAM and answers ``reply``."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received = bytearray()

    def serve():
        conn, _ = server.accept()
        with conn:
            buf = b""
            while b"\0" not in buf:
                buf += conn.recv(1)
            assert buf == b"zINSTREAM\0"
            while True:
                size = struct.unpack("!L", conn.recv(4, socket.MSG_WAITALL))[0]
                if size == 0:
                    break
                received.extend(conn.recv(size, socket.MSG_WAITALL))
            conn.sendall(reply)
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1], received


@pytest.fixture
def report_file():
    return SimpleUploadedFile("r.pdf", b"%PDF-1.4 plain report", content_type="application/pdf")


def test_a_clean_file_passes_and_is_sent_whole(monkeypatch, report_file):
    port, received = _fake_clamd(b"stream: OK\0")
    monkeypatch.setenv("CLAMD_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMD_PORT", str(port))
    clamav.scan(report_file)
    assert bytes(received) == b"%PDF-1.4 plain report"
    assert report_file.tell() == 0


def test_an_infected_file_is_refused(monkeypatch, report_file):
    port, _ = _fake_clamd(b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
    monkeypatch.setenv("CLAMD_PORT", str(port))
    monkeypatch.setenv("CLAMD_HOST", "127.0.0.1")
    with pytest.raises(ValidationFailed, match="virus check"):
        clamav.scan(report_file)


def test_an_error_answer_is_not_treated_as_clean(monkeypatch, report_file):
    port, _ = _fake_clamd(b"INSTREAM size limit exceeded. ERROR\0")
    monkeypatch.setenv("CLAMD_PORT", str(port))
    monkeypatch.setenv("CLAMD_HOST", "127.0.0.1")
    with pytest.raises(ValidationFailed, match="could not check"):
        clamav.scan(report_file)


def test_an_unreachable_clamd_refuses_the_upload(monkeypatch, report_file):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listening
    monkeypatch.setenv("CLAMD_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMD_PORT", str(port))
    with pytest.raises(ValidationFailed, match="could not check"):
        clamav.scan(report_file)


def test_a_missing_clamd_socket_refuses_the_upload(monkeypatch, report_file, tmp_path):
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("this platform has no Unix sockets")
    monkeypatch.setenv("CLAMD_SOCKET", str(tmp_path / "no-such-clamd.ctl"))
    with pytest.raises(ValidationFailed, match="could not check"):
        clamav.scan(report_file)
