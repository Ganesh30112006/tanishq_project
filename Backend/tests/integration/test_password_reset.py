"""Forgetting a password must not lose a person their records."""
from __future__ import annotations

import re

import pytest
from django.core import mail

pytestmark = pytest.mark.django_db

OLD = "the old passphrase 2026"
NEW = "a brand new passphrase 2026"


def _link(body: str) -> tuple[str, str]:
    match = re.search(r"uid=([0-9a-f-]+)&token=(\S+)", body)
    assert match, body
    return match.group(1), match.group(2)


def test_reset_end_to_end(api_client, make_user):
    user = make_user(email="forgot@example.test", password=OLD)
    session = api_client.post(
        "/api/v1/auth/login", {"email": user.email, "password": OLD}, format="json"
    ).data["access_token"]

    resp = api_client.post("/api/v1/auth/password-reset", {"email": "Forgot@Example.test"}, format="json")
    assert resp.status_code == 202
    assert len(mail.outbox) == 1
    uid, token = _link(mail.outbox[0].body)
    assert uid == str(user.public_id)  # never the sequential primary key

    resp = api_client.post(
        "/api/v1/auth/password-reset/confirm",
        {"uid": uid, "token": token, "password": NEW}, format="json",
    )
    assert resp.status_code == 200, resp.data

    # The old password and every old session are gone; the new one works.
    assert api_client.post("/api/v1/auth/login", {"email": user.email, "password": OLD}, format="json").status_code == 401
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {session}")
    assert api_client.get("/api/v1/auth/me").status_code == 401
    api_client.credentials()
    assert api_client.post("/api/v1/auth/login", {"email": user.email, "password": NEW}, format="json").status_code == 201

    # The link is single-use.
    again = api_client.post(
        "/api/v1/auth/password-reset/confirm",
        {"uid": uid, "token": token, "password": "yet another passphrase 1"}, format="json",
    )
    assert again.status_code == 400


def test_unknown_email_gets_the_same_answer_and_no_mail(api_client, make_user):
    make_user(email="known@example.test")
    known = api_client.post("/api/v1/auth/password-reset", {"email": "known@example.test"}, format="json")
    unknown = api_client.post("/api/v1/auth/password-reset", {"email": "nobody@example.test"}, format="json")
    assert known.status_code == unknown.status_code == 202
    assert known.data == unknown.data
    assert len(mail.outbox) == 1


def test_a_forged_token_is_refused(api_client, make_user):
    user = make_user(email="target@example.test", password=OLD)
    resp = api_client.post(
        "/api/v1/auth/password-reset/confirm",
        {"uid": str(user.public_id), "token": "abc-forged", "password": NEW}, format="json",
    )
    assert resp.status_code == 400
    assert api_client.post("/api/v1/auth/login", {"email": user.email, "password": OLD}, format="json").status_code == 201


def test_a_weak_new_password_is_refused(api_client, make_user):
    user = make_user(email="weak@example.test", password=OLD)
    api_client.post("/api/v1/auth/password-reset", {"email": user.email}, format="json")
    uid, token = _link(mail.outbox[0].body)
    resp = api_client.post(
        "/api/v1/auth/password-reset/confirm",
        {"uid": uid, "token": token, "password": "123456789012"}, format="json",
    )
    assert resp.status_code == 400
