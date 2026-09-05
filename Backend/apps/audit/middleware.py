"""Correlation-id + request-context middleware.

Assigns every request a correlation id (honouring an inbound
``X-Request-ID`` / ``X-Correlation-ID`` if it is well-formed), exposes it as
``request.request_id``, binds the request-scoped context, and echoes it back
on the response. The same id is forwarded to the FastAPI intelligence service
so a computation can be traced end to end.
"""
from __future__ import annotations

import re
import uuid

from apps.audit import context

_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{8,128}$")


class RequestContextMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request):
        request_id = self._resolve_id(request)
        request.request_id = request_id
        context.bind(
            request_id=request_id,
            client_ip=self._client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:256],
        )
        try:
            response = self.get_response(request)
        finally:
            # If authentication ran, record who the actor turned out to be.
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                context.set_actor(str(getattr(user, "public_id", user.pk)), user.get_username())
            response_context_id = request_id
            context.clear()
        response["X-Request-ID"] = response_context_id
        return response

    @staticmethod
    def _resolve_id(request) -> str:
        for header in ("HTTP_X_REQUEST_ID", "HTTP_X_CORRELATION_ID"):
            candidate = request.META.get(header, "")
            if candidate and _ID_RE.match(candidate):
                return candidate
        return uuid.uuid4().hex

    @staticmethod
    def _client_ip(request) -> str | None:
        # X-Forwarded-For is only trusted behind a controlled proxy; by default
        # we use the direct peer address.
        return request.META.get("REMOTE_ADDR")
