from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_openapi_schema_is_served(client):
    resp = client.get("/api/schema")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "openapi:" in body
    for path in ("/api/v1/risk/assessments/", "/api/v1/reports/", "/api/v1/labs/orders/"):
        assert path in body
