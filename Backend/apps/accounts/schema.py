"""drf-spectacular hints so the OpenAPI schema describes bearer auth."""
from __future__ import annotations

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class BearerTokenScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.BearerTokenAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT or opaque",
            "description": "OIDC access token, or a local dev token (prefix cst_) when enabled.",
        }
