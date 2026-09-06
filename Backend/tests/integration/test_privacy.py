"""Consent, retention and erasure.

The hard case in a clinical system is erasure. Clinical history is append-only
and separately subject to a retention obligation, so "delete my data" cannot be
a DELETE. These tests pin the resolution: identifiers are destroyed, clinical
observations survive unlinkably, and the person is told exactly that rather
than being told their data was deleted when it was not.
"""
from __future__ import annotations

import datetime as dt

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.common.enums import Role
from apps.common.errors import ValidationFailed
from apps.privacy.models import (
    ConsentGrant,
    ConsentPurpose,
    ErasureRequest,
    ErasureState,
)
from apps.privacy.services import REDACTED, PrivacyService

pytestmark = pytest.mark.django_db

service = PrivacyService()


@pytest.fixture
def published():
    call_command("seed_consent")


@pytest.fixture
def linked_patient(make_user, make_patient):
    user = make_user(Role.PATIENT)
    patient = make_patient(user=user)
    patient.given_name = "Meera"
    patient.family_name = "Nair"
    patient.date_of_birth = dt.date(1975, 4, 2)
    patient.phone = "+91 98765 43210"
    patient.save()
    return patient


# --- consent -------------------------------------------------------------
def test_no_grant_is_not_consent(published, linked_patient):
    """Silence must never be read as agreement."""
    assert service.has_consent(linked_patient, ConsentPurpose.RISK_ANALYSIS) is False


def test_granting_and_withdrawing(published, linked_patient):
    service.record_consent(
        patient=linked_patient, purpose=ConsentPurpose.RISK_ANALYSIS, granted=True
    )
    assert service.has_consent(linked_patient, ConsentPurpose.RISK_ANALYSIS)

    service.record_consent(
        patient=linked_patient, purpose=ConsentPurpose.RISK_ANALYSIS, granted=False
    )
    assert not service.has_consent(linked_patient, ConsentPurpose.RISK_ANALYSIS)

    # The row is kept, not deleted: withdrawal is part of the history.
    grant = ConsentGrant.objects.get(
        patient=linked_patient, purpose=ConsentPurpose.RISK_ANALYSIS
    )
    assert grant.granted_at is not None
    assert grant.withdrawn_at is not None


def test_withdrawing_one_purpose_leaves_the_others_alone(published, linked_patient):
    for purpose in (ConsentPurpose.RISK_ANALYSIS, ConsentPurpose.AI_ASSISTANCE):
        service.record_consent(patient=linked_patient, purpose=purpose, granted=True)

    service.record_consent(
        patient=linked_patient, purpose=ConsentPurpose.AI_ASSISTANCE, granted=False
    )
    assert service.has_consent(linked_patient, ConsentPurpose.RISK_ANALYSIS)
    assert not service.has_consent(linked_patient, ConsentPurpose.AI_ASSISTANCE)


def test_consent_records_the_exact_wording_agreed_to(published, linked_patient):
    grant = service.record_consent(
        patient=linked_patient, purpose=ConsentPurpose.RESEARCH, granted=True
    )
    assert grant.document.version == "1.0"
    assert grant.document.body

    # Proving consent means showing the text as it stood, so it cannot be edited.
    from apps.common.errors import OptimisticLockError

    with pytest.raises(OptimisticLockError):
        grant.document.body = "something else"
        grant.document.save()


def test_the_summary_lists_purposes_never_answered(published, linked_patient):
    summary = {row["purpose"]: row for row in service.consent_summary(linked_patient)}
    assert set(summary) == set(ConsentPurpose.values)
    assert summary[ConsentPurpose.RESEARCH]["answered"] is False
    assert summary[ConsentPurpose.RESEARCH]["granted"] is False
    assert summary[ConsentPurpose.CARE]["is_essential"] is True


def test_consent_cannot_be_recorded_against_unpublished_wording(linked_patient):
    """Agreement to text that does not exist is not agreement."""
    with pytest.raises(ValidationFailed):
        service.record_consent(
            patient=linked_patient, purpose=ConsentPurpose.RESEARCH, granted=True
        )


def test_enforcement_is_off_until_the_wording_is_published(linked_patient):
    # Nothing published: a deployment that has not authored consent text yet is
    # not blocked, but the gap is reported rather than hidden.
    service.enforce_if_published(linked_patient, ConsentPurpose.RISK_ANALYSIS)
    assert ConsentPurpose.RISK_ANALYSIS in service.unconfigured_purposes()


def test_enforcement_bites_once_published(published, linked_patient):
    assert service.unconfigured_purposes() == []
    with pytest.raises(ValidationFailed):
        service.enforce_if_published(linked_patient, ConsentPurpose.RISK_ANALYSIS)

    service.record_consent(
        patient=linked_patient, purpose=ConsentPurpose.RISK_ANALYSIS, granted=True
    )
    service.enforce_if_published(linked_patient, ConsentPurpose.RISK_ANALYSIS)


# --- erasure -------------------------------------------------------------
def test_erasure_destroys_the_identifiers(published, linked_patient):
    request = service.request_erasure(patient=linked_patient)
    service.execute_erasure(request)

    linked_patient.refresh_from_db()
    assert linked_patient.given_name == REDACTED
    assert linked_patient.family_name == REDACTED
    assert linked_patient.date_of_birth is None
    assert linked_patient.phone == ""
    assert linked_patient.mrn.startswith("ERASED-")
    assert "Meera" not in str(linked_patient.mrn)
    assert linked_patient.user_id is None
    assert linked_patient.is_active is False


def test_erasure_keeps_the_clinical_series(published, linked_patient, make_measurement):
    """The point of the design: the readings survive, detached from the person."""
    make_measurement(linked_patient, value="142")
    request = service.request_erasure(patient=linked_patient)
    service.execute_erasure(request)

    linked_patient.refresh_from_db()
    assert linked_patient.measurements.count() == 1
    assert linked_patient.measurements.first().value_num is not None


def test_erasure_tells_the_person_what_actually_happened(published, linked_patient):
    """Never say "deleted" when the answer is "de-identified"."""
    request = service.request_erasure(patient=linked_patient)
    service.execute_erasure(request)

    summary = request.outcome_summary.lower()
    assert "destroyed" in summary
    assert "kept" in summary
    assert "no longer connected to you" in summary
    assert request.retained_until is not None
    assert request.state == ErasureState.COMPLETED


def test_erasure_revokes_the_login_and_its_sessions(published, linked_patient):
    from apps.accounts.models import AccessToken
    from apps.accounts.services import AccountService

    user = linked_patient.user
    AccountService().issue_local_token(user)
    AccountService().issue_refresh_token(user)
    assert AccessToken.objects.filter(user=user, revoked_at__isnull=True).exists()

    service.execute_erasure(service.request_erasure(patient=linked_patient))

    user.refresh_from_db()
    assert user.is_active is False
    assert user.email.startswith("erased-")
    assert not AccessToken.objects.filter(user=user, revoked_at__isnull=True).exists()


def test_requesting_erasure_twice_returns_the_same_open_request(published, linked_patient):
    first = service.request_erasure(patient=linked_patient)
    second = service.request_erasure(patient=linked_patient)
    assert first.pk == second.pk
    assert ErasureRequest.objects.filter(patient=linked_patient).count() == 1


def test_executing_an_already_completed_request_is_a_no_op(published, linked_patient):
    request = service.request_erasure(patient=linked_patient)
    service.execute_erasure(request)
    mrn = linked_patient.__class__.objects.get(pk=linked_patient.pk).mrn

    service.execute_erasure(request)
    assert linked_patient.__class__.objects.get(pk=linked_patient.pk).mrn == mrn


def test_a_refusal_has_to_say_why(published, linked_patient):
    request = service.request_erasure(patient=linked_patient)
    with pytest.raises(ValidationFailed):
        service.refuse_erasure(request, note="   ")


def test_a_refused_request_cannot_then_be_executed(published, linked_patient):
    request = service.request_erasure(patient=linked_patient)
    service.refuse_erasure(request, note="Open medico-legal matter.")
    with pytest.raises(ValidationFailed):
        service.execute_erasure(request)


# --- the API ------------------------------------------------------------
def test_a_patient_can_see_and_change_their_own_consent(auth_client, published, linked_patient):
    client = auth_client(linked_patient.user)

    resp = client.get("/api/v1/privacy/consent")
    assert resp.status_code == 200
    assert len(resp.data["purposes"]) == len(ConsentPurpose.values)

    resp = client.post(
        "/api/v1/privacy/consent",
        {"purpose": ConsentPurpose.RISK_ANALYSIS, "granted": True},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["granted"] is True
    assert service.has_consent(linked_patient, ConsentPurpose.RISK_ANALYSIS)


def test_a_patient_can_ask_to_be_erased_and_is_told_what_that_means(
    auth_client, published, linked_patient
):
    client = auth_client(linked_patient.user)
    resp = client.get("/api/v1/privacy/erasure")
    assert resp.status_code == 200
    assert "kept" in resp.data["what_this_means"]

    resp = client.post("/api/v1/privacy/erasure", {"reason": "Moving abroad."}, format="json")
    assert resp.status_code == 201
    assert resp.data["state"] == ErasureState.REQUESTED


def test_a_patient_cannot_execute_their_own_erasure(
    auth_client, published, linked_patient
):
    """Irreversible destruction is never self-service."""
    request = service.request_erasure(patient=linked_patient)
    client = auth_client(linked_patient.user)
    resp = client.post(
        f"/api/v1/privacy/erasure/requests/{request.public_id}",
        {"decision": "execute"},
        format="json",
    )
    assert resp.status_code in (403, 404)
    linked_patient.refresh_from_db()
    assert linked_patient.given_name != REDACTED


def test_consent_endpoints_need_a_linked_record(auth_client, published, make_user):
    """A login with no patient record has no consent to show."""
    stranger = make_user(Role.PATIENT)
    assert auth_client(stranger).get("/api/v1/privacy/consent").status_code == 404


# --- retention -----------------------------------------------------------
def test_the_retention_report_states_a_basis_for_every_period():
    from apps.privacy.retention import seed_default_policies, sweep

    seed_default_policies()
    report = sweep()
    assert report["policies"]
    for row in report["policies"]:
        assert row["basis"].strip(), f"{row['category']} keeps data for an unstated reason"
        assert row["retain_days"] > 0


def test_the_sweep_reports_without_touching_anything(make_user):
    """A retention job must not destroy anything the first time it is run."""
    from apps.accounts.models import AccessToken
    from apps.accounts.services import AccountService
    from apps.privacy.retention import seed_default_policies, sweep

    seed_default_policies()
    user = make_user(Role.PATIENT)
    issued = AccountService().issue_local_token(user)
    AccessToken.objects.filter(pk=issued.record.pk).update(
        expires_at=timezone.now() - dt.timedelta(days=400)
    )

    report = sweep(apply=False)
    assert report["deleted"] == {}
    assert AccessToken.objects.filter(pk=issued.record.pk).exists()

    applied = sweep(apply=True)
    assert applied["deleted"].get("ACCESS_TOKEN", 0) >= 1
    assert not AccessToken.objects.filter(pk=issued.record.pk).exists()


def test_clinical_data_is_never_deleted_automatically():
    """Only categories with no evidentiary value are ever removed by the job."""
    from apps.privacy.models import RetentionCategory, RetentionPolicy
    from apps.privacy.retention import seed_default_policies

    seed_default_policies()
    for category in (
        RetentionCategory.CLINICAL_RECORD,
        RetentionCategory.UPLOADED_REPORT,
        RetentionCategory.AUDIT_LOG,
    ):
        policy = RetentionPolicy.objects.get(category=category)
        assert policy.hard_delete is False, f"{category} would be destroyed by a cron job"


def test_the_audit_log_outlives_the_record_it_describes():
    from apps.privacy.models import RetentionCategory, RetentionPolicy
    from apps.privacy.retention import seed_default_policies

    seed_default_policies()
    audit = RetentionPolicy.objects.get(category=RetentionCategory.AUDIT_LOG)
    clinical = RetentionPolicy.objects.get(category=RetentionCategory.CLINICAL_RECORD)
    assert audit.retain_days > clinical.retain_days
