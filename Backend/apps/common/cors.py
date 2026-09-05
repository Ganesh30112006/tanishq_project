"""Cross-origin access for the browser client.

The SPA is served from its own origin (a Vite dev server locally, a static
host in real deployments) and calls this API with a bearer token in the
``Authorization`` header. Browsers therefore need an explicit CORS grant.

The allowlist is exact-origin and comes from the environment: there is no
wildcard and no ``Access-Control-Allow-Credentials``, so a hostile page cannot
have the browser attach ambient credentials. Tokens are sent explicitly by the
client, never as cookies, which keeps this middleware from widening the
authentication surface.
"""
from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

_DEFAULT_HEADERS = ("authorization", "content-type", "x-request-id", "accept")
_DEFAULT_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


class CorsMiddleware:
    """Adds CORS headers for allowlisted origins and answers preflights."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        config = getattr(settings, "CORS", {})
        self.allowed_origins = frozenset(config.get("ALLOWED_ORIGINS", ()))
        self.allowed_headers = ", ".join(config.get("ALLOWED_HEADERS", _DEFAULT_HEADERS))
        self.allowed_methods = ", ".join(config.get("ALLOWED_METHODS", _DEFAULT_METHODS))
        self.max_age = str(config.get("PREFLIGHT_MAX_AGE_SECONDS", 600))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        origin = request.headers.get("Origin", "")
        allowed = bool(origin) and origin in self.allowed_origins

        if allowed and request.method == "OPTIONS" and "Access-Control-Request-Method" in request.headers:
            response: HttpResponse = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        # Always vary on Origin so a cached response is never replayed to a
        # different origin.
        existing_vary = response.headers.get("Vary")
        response.headers["Vary"] = f"{existing_vary}, Origin" if existing_vary else "Origin"

        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = self.allowed_headers
            response.headers["Access-Control-Allow-Methods"] = self.allowed_methods
            response.headers["Access-Control-Max-Age"] = self.max_age
            response.headers["Access-Control-Expose-Headers"] = "X-Request-Id"
        return response
