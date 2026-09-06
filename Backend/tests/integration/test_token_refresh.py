"""Sessions that outlive an access token, without outliving their safety.

An hour-long access token with no way to renew it logs people out mid-consultation,
so there is now a refresh token. A long-lived credential is only acceptable
because it is single-use: the interesting tests here are the ones about what
happens when the same refresh token is presented twice, which is what a stolen
one looks like.
"""
from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.accounts.models import AccessToken, RefreshToken
from apps.accounts.services import AccountService
from apps.common.enums import Role
from apps.common.errors import AuthenticationRequired

pytestmark = pytest.mark.django_db

PASSWORD = "CorrectHorseBatteryStaple9"  # noqa: S105 - a fixture, not a credential


@pytest.fixture
def account(make_user):
    user = make_user(Role.PATIENT)
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    return user


def _login(api_client, account):
    resp = api_client.post(
        "/api/v1/auth/login",
        {"email": account.email, "password": PASSWORD},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return resp.data


# --- the happy path ------------------------------------------------------
def test_login_returns_both_tokens(api_client, account):
    body = _login(api_client, account)
    assert body["access_token"].startswith("cst_")
    assert body["refresh_token"].startswith("cs_refresh_")
    # Distinct prefixes, so neither can be mistaken for the other.
    assert not body["refresh_token"].startswith("cst_")
    assert body["refresh_expires_at"] > body["expires_at"]


def test_a_refresh_token_buys_a_new_access_token(api_client, account):
    body = _login(api_client, account)
    resp = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": body["refresh_token"]}, format="json"
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["access_token"] != body["access_token"]
    assert resp.data["refresh_token"] != body["refresh_token"], "token must rotate"

    # And the new access token actually works.
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access_token']}")
    assert api_client.get("/api/v1/auth/me").status_code == 200


def test_refreshing_retires_the_access_token_it_replaces(api_client, account):
    """Otherwise every refresh leaves another live credential lying about."""
    body = _login(api_client, account)
    api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": body["refresh_token"]}, format="json"
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access_token']}")
    assert api_client.get("/api/v1/auth/me").status_code == 401


def test_refresh_does_not_need_a_valid_access_token(api_client, account):
    """The usual reason to refresh is that the access token has already expired."""
    body = _login(api_client, account)
    api_client.credentials(HTTP_AUTHORIZATION="Bearer cs_not_a_real_token")
    resp = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": body["refresh_token"]}, format="json"
    )
    assert resp.status_code == 200


# --- the theft path ------------------------------------------------------
def test_reusing_a_refresh_token_signs_out_the_whole_family(api_client, account):
    """The security property this design exists for.

    The honest client discards its refresh token the moment it redeems it. So a
    second presentation of that same token means somebody else has a copy. We
    cannot tell which caller is the thief, so both lose the session.
    """
    body = _login(api_client, account)
    first = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": body["refresh_token"]}, format="json"
    )
    assert first.status_code == 200

    replay = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": body["refresh_token"]}, format="json"
    )
    assert replay.status_code == 401
    assert "signed out" in str(replay.data).lower()

    # The token the *legitimate* client is holding is dead too.
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {first.data['access_token']}")
    assert api_client.get("/api/v1/auth/me").status_code == 401

    later = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": first.data["refresh_token"]}, format="json"
    )
    assert later.status_code == 401, "the descendant token must be revoked as well"


def test_an_unrelated_session_survives_a_family_revocation(api_client, account):
    """Signing out a compromised session must not sign out the user's phone."""
    laptop = _login(api_client, account)
    phone = _login(api_client, account)

    api_client.post("/api/v1/auth/refresh", {"refresh_token": laptop["refresh_token"]},
                    format="json")
    api_client.post("/api/v1/auth/refresh", {"refresh_token": laptop["refresh_token"]},
                    format="json")

    still_good = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": phone["refresh_token"]}, format="json"
    )
    assert still_good.status_code == 200


# --- expiry and revocation ----------------------------------------------
def test_an_expired_refresh_token_is_refused(account):
    service = AccountService()
    issued = service.issue_refresh_token(account)
    issued.record.expires_at = timezone.now() - dt.timedelta(seconds=1)
    issued.record.save(update_fields=["expires_at"])

    with pytest.raises(AuthenticationRequired):
        service.redeem_refresh_token(issued.raw)


def test_a_made_up_refresh_token_is_refused(api_client, account):
    resp = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": "cs_refresh_nonsense"}, format="json"
    )
    assert resp.status_code == 401


def test_refresh_without_a_token_is_a_validation_error(api_client, account):
    assert api_client.post("/api/v1/auth/refresh", {}, format="json").status_code == 400


def test_a_deactivated_user_cannot_refresh(account):
    service = AccountService()
    issued = service.issue_refresh_token(account)
    account.is_active = False
    account.save(update_fields=["is_active"])

    with pytest.raises(AuthenticationRequired):
        service.redeem_refresh_token(issued.raw)


def test_logging_out_kills_the_refresh_token_too(api_client, account):
    """Otherwise "sign out" leaves a credential that mints a new session."""
    body = _login(api_client, account)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access_token']}")
    assert api_client.post("/api/v1/auth/logout", {}, format="json").status_code == 204

    api_client.credentials()
    resp = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": body["refresh_token"]}, format="json"
    )
    assert resp.status_code == 401


def test_revoke_all_sessions_covers_both_kinds_of_token(account):
    service = AccountService()
    service.issue_local_token(account)
    service.issue_refresh_token(account)

    service.revoke_all_for_user(account)

    assert not AccessToken.objects.filter(user=account, revoked_at__isnull=True).exists()
    assert not RefreshToken.objects.filter(user=account, revoked_at__isnull=True).exists()


# --- storage ------------------------------------------------------------
def test_the_raw_refresh_token_is_never_stored(account):
    issued = AccountService().issue_refresh_token(account)
    stored = RefreshToken.objects.get(pk=issued.record.pk)
    assert issued.raw not in stored.token_hash
    assert len(stored.token_hash) == 64
    assert not RefreshToken.objects.filter(token_hash=issued.raw).exists()


def test_a_refresh_token_is_not_accepted_as_a_bearer_credential(api_client, account):
    """Different prefix, different purpose - it must not authenticate a request."""
    body = _login(api_client, account)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['refresh_token']}")
    assert api_client.get("/api/v1/auth/me").status_code == 401
