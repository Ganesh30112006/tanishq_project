"""Bearer-token authentication.

Two token shapes are supported behind one DRF authenticator:

* **Federated OIDC access tokens** - validated against the configured issuer.
  Signature/issuer/audience/expiry verification is delegated to
  :func:`verify_oidc_token`, which must be wired to a real JWKS client before
  production use. It fails closed.
* **Local opaque tokens** (prefix ``cst_``) - only accepted when
  ``IDENTITY["LOCAL_DEV_TOKENS"]`` is true. Looked up by SHA-256 hash in
  :class:`~apps.accounts.models.AccessToken`; revoked or expired tokens are
  rejected immediately (spec section 7).
"""
from __future__ import annotations

import hashlib

from django.conf import settings
from django.utils import timezone
from rest_framework import authentication, exceptions

LOCAL_TOKEN_PREFIX = "cst_"  # noqa: S105 - not a secret, just a discriminator


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_oidc_token(raw_token: str) -> dict:
    """Validate a federated access token against the configured OIDC issuer
    (JWKS signature, ``iss``, ``aud``, ``exp``). Fails closed."""
    from apps.accounts.oidc import (
        OIDCConfigurationError,
        OIDCValidationError,
        get_validator,
    )

    try:
        validator = get_validator()
    except OIDCConfigurationError as exc:
        raise exceptions.AuthenticationFailed(
            "Federated token validation is not configured."
        ) from exc
    try:
        return validator.validate(raw_token)
    except OIDCValidationError as exc:
        raise exceptions.AuthenticationFailed(f"Invalid federated token: {exc}") from exc


class BearerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Malformed Authorization header.")
        raw_token = header[1].decode("latin-1")

        if raw_token.startswith(LOCAL_TOKEN_PREFIX):
            return self._authenticate_local(raw_token)
        return self._authenticate_federated(raw_token)

    def authenticate_header(self, request) -> str:
        return self.keyword

    # -- local opaque tokens -------------------------------------------------
    def _authenticate_local(self, raw_token: str):
        if not settings.IDENTITY.get("LOCAL_DEV_TOKENS"):
            raise exceptions.AuthenticationFailed("Local tokens are not accepted here.")

        from apps.accounts.models import AccessToken

        try:
            token = AccessToken.objects.select_related("user").get(
                token_hash=hash_token(raw_token)
            )
        except AccessToken.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid token.") from None

        if not token.is_valid():
            raise exceptions.AuthenticationFailed("Token is expired or revoked.")
        if not token.user.is_active:
            raise exceptions.AuthenticationFailed("User is inactive.")

        AccessToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token.user, token

    # -- federated tokens --------------------------------------------------
    def _authenticate_federated(self, raw_token: str):
        from apps.accounts.models import User

        claims = verify_oidc_token(raw_token)
        subject = claims.get("sub")
        if not subject:
            raise exceptions.AuthenticationFailed("Token missing subject claim.")
        try:
            user = User.objects.get(external_subject=subject, is_active=True)
        except User.DoesNotExist:
            raise exceptions.AuthenticationFailed("No active local account for this identity.") from None
        return user, claims
