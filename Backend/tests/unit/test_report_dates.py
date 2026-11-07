"""Indian laboratories print the day first. Found on 2026-11-08: "03/04/2026" was
stored as 4 March, and "17/10/2024" was not read at all."""
from __future__ import annotations

import datetime as dt

import pytest

from apps.reports.pipeline import _parse_dt


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("03/04/2026", dt.date(2026, 4, 3)),
        ("17/10/2024", dt.date(2024, 10, 17)),
        ("2026-04-03", dt.date(2026, 4, 3)),
        ("2026-04-03 09:15", dt.date(2026, 4, 3)),
    ],
)
def test_the_day_comes_first(printed, expected):
    parsed = _parse_dt(printed)
    assert parsed is not None
    assert parsed.date() == expected


@pytest.mark.parametrize("printed", ["10/17/2024", "31/02/2026", "not a date", ""])
def test_a_date_that_cannot_be_real_is_not_guessed(printed):
    assert _parse_dt(printed) is None


def test_reading_a_document_gets_far_longer_than_an_ordinary_call(monkeypatch, settings):
    # At the ordinary 30 seconds every scanned report failed as "unavailable".
    import httpx

    from apps.common.intelligence import IntelligenceClient

    settings.INTELLIGENCE = {
        "BASE_URL": "http://service", "SERVICE_TOKEN": "t", "TIMEOUT_SECONDS": 30.0, "DOCUMENT_TIMEOUT_SECONDS": 1800.0,
    }
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen["timeout"] = timeout
        return httpx.Response(200, json={"document_id": "d", "disposition": "UNREADABLE"})

    monkeypatch.setattr(httpx, "post", fake_post)
    IntelligenceClient().process_document(
        document_id="d", content=b"x", declared_media_type="application/pdf", correlation_id="c",
    )
    assert seen["timeout"] == 1800.0
