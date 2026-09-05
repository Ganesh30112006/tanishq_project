"""OpenID Connect access-token validation (spec: OAuth 2.0 / OIDC identity).

Validates a bearer JWT against the configured issuer:

* signature - via the issuer's JWKS (RS256 / ES256), keys cached by ``PyJWKClient``
* ``iss`` must equal the configured issuer
* ``aud`` must contain the configured audience
* ``exp`` / ``nbf`` / ``iat`` are enforced

It **fails closed**: if OIDC is not configured, or anything about the token
does not check out, validation raises and authentication is refused. Local
opaque dev tokens are handled separately and are never accepted in production.
"""
from __future__ import annotations

from functools import lru_cache

from django.conf import settings

ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384"]
LEEWAY_SECONDS = 30


class OIDCConfigurationError(RuntimeError):
    pass


class OIDCValidationError(RuntimeError):
    pass


class OIDCValidator:
    def __init__(self, *, issuer: str, audience: str, jwks_url: str) -> None:
        if not (issuer and audience and jwks_url):
            raise OIDCConfigurationError("OIDC issuer, audience and JWKS URL must all be configured.")
        self.issuer = issuer
        self.audience = audience
        self.jwks_url = jwks_url
        self._jwk_client = None

    def _signing_key(self, token: str):
        import jwt

        if self._jwk_client is None:
            self._jwk_client = jwt.PyJWKClient(self.jwks_url, cache_keys=True)
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def validate(self, token: str) -> dict:
        import jwt

        try:
            key = self._signing_key(token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise OIDCValidationError(str(exc)) from exc
        if not claims.get("sub"):
            raise OIDCValidationError("Token has no subject claim.")
        return claims


@lru_cache(maxsize=1)
def get_validator() -> OIDCValidator:
    cfg = settings.IDENTITY
    return OIDCValidator(
        issuer=cfg.get("OIDC_ISSUER", ""),
        audience=cfg.get("OIDC_AUDIENCE", ""),
        jwks_url=cfg.get("OIDC_JWKS_URL", ""),
    )
