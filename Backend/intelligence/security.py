"""Boundary security for the intelligence service (spec section 52).

Only Django calls this service. Requests must present the shared service token
and a correlation id. There is no per-user auth here because this service
never makes authorization decisions.
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from intelligence.settings import get_settings


async def verify_service_request(
    x_service_token: str = Header(default=""),
    x_correlation_id: str = Header(default=""),
) -> str:
    settings = get_settings()
    # An unconfigured token would make compare_digest("", "") succeed, so a
    # missing setting would silently open the service to anyone who can reach
    # the port. Refuse to serve instead - a misconfiguration must be loud.
    if not settings.service_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INTELLIGENCE_SERVICE_TOKEN is not configured; refusing to serve.",
        )
    if not secrets.compare_digest(x_service_token, settings.service_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token."
        )
    if settings.require_correlation_id and not x_correlation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-Correlation-Id."
        )
    return x_correlation_id
