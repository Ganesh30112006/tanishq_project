"""Real OIDC access-token validation (JWKS signature + iss/aud/exp)."""
from __future__ import annotations

import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.accounts.models import User
from apps.accounts.oidc import OIDCValidator

pytestmark = pytest.mark.django_db

ISSUER = "https://issuer.test"
AUDIENCE = "caresense-api"


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def validator(rsa_key, monkeypatch):
    v = OIDCValidator(issuer=ISSUER, audience=AUDIENCE, jwks_url="https://issuer.test/jwks.json")
    monkeypatch.setattr(v, "_signing_key", lambda token: rsa_key.public_key())
    return v


def _token(rsa_key, **overrides):
    now = dt.datetime.now(dt.UTC)
    claims = {
        "sub": "user-123", "iss": ISSUER, "aud": AUDIENCE,
        "iat": now, "exp": now + dt.timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, rsa_key, algorithm="RS256")


def test_valid_token_returns_claims(validator, rsa_key):
    claims = validator.validate(_token(rsa_key))
    assert claims["sub"] == "user-123"


def test_wrong_audience_is_rejected(validator, rsa_key):
    from apps.accounts.oidc import OIDCValidationError

    with pytest.raises(OIDCValidationError):
        validator.validate(_token(rsa_key, aud="someone-else"))


def test_expired_token_is_rejected(validator, rsa_key):
    from apps.accounts.oidc import OIDCValidationError

    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    with pytest.raises(OIDCValidationError):
        validator.validate(_token(rsa_key, exp=past, iat=past - dt.timedelta(minutes=5)))


def test_federated_login_maps_subject_to_local_account(rsa_key, monkeypatch, settings):
    settings.IDENTITY = {**settings.IDENTITY, "OIDC_ISSUER": ISSUER, "OIDC_AUDIENCE": AUDIENCE,
                         "OIDC_JWKS_URL": "https://issuer.test/jwks.json"}
    from apps.accounts import authentication, oidc

    oidc.get_validator.cache_clear()
    monkeypatch.setattr(
        oidc.OIDCValidator, "_signing_key", lambda self, token: rsa_key.public_key()
    )

    user = User.objects.create_user(email="fed@example.test", password="x" * 12)
    user.external_subject = "fed-sub-1"
    user.save(update_fields=["external_subject"])

    auth = authentication.BearerTokenAuthentication()

    class _Req:
        META = {"HTTP_AUTHORIZATION": f"Bearer {_token(rsa_key, sub='fed-sub-1')}"}

    resolved, claims = auth.authenticate(_Req())
    assert resolved.pk == user.pk
    oidc.get_validator.cache_clear()
