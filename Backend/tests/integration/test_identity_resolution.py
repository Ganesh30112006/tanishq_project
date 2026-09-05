from __future__ import annotations

import datetime as dt

import pytest

from apps.common.enums import Role
from apps.medical_records.models import Condition
from apps.patients.identity import IdentityMergeService, IdentityResolver, jaro_winkler
from apps.patients.models import Patient, PatientIdentityCandidate
from apps.reconciliation.models import ReconciliationEvent

pytestmark = pytest.mark.django_db

DOB = dt.date(1980, 4, 12)


def _patient(mrn, given, family, *, dob=DOB, phone=""):
    return Patient.objects.create(
        mrn=mrn, given_name=given, family_name=family, date_of_birth=dob, phone=phone, sex="FEMALE"
    )


def test_jaro_winkler_prefers_prefix_matches():
    assert jaro_winkler("martha", "marhta") > 0.9
    assert jaro_winkler("smith", "jones") < 0.5


def test_similar_names_same_dob_become_a_pending_candidate_not_a_merge(make_user):
    a = _patient("M1", "Catherine", "Nguyen")
    _patient("M2", "Katherine", "Nguyen")

    rows = IdentityResolver().scan_and_record(a, created_by=make_user(Role.ADMIN))
    assert len(rows) == 1
    cand = rows[0]
    assert cand.status == PatientIdentityCandidate.Status.PENDING
    assert cand.tier in {
        PatientIdentityCandidate.Tier.SIMILARITY,
        PatientIdentityCandidate.Tier.DETERMINISTIC_COMPOSITE,
    }
    assert ReconciliationEvent.objects.filter(kind="IDENTITY_CONFLICT").exists()
    # Both patient rows still exist and are active.
    assert Patient.objects.filter(is_active=True).count() == 2


def test_distinct_people_are_not_matched(make_user):
    a = _patient("D1", "John", "Smith", dob=dt.date(1990, 1, 1))
    _patient("D2", "Robert", "Johnson", dob=dt.date(1975, 6, 6))
    rows = IdentityResolver().scan_and_record(a, created_by=make_user(Role.ADMIN))
    assert rows == []


def test_merge_only_after_approval_and_repoints_clinical_rows(make_user):
    admin = make_user(Role.ADMIN)
    keep = _patient("K1", "Maria", "Garcia")
    dup = _patient("K2", "Maria", "Garcia")
    Condition.objects.create(patient=dup, label="Hypertension", clinical_status="ACTIVE")

    cand = IdentityResolver().scan_and_record(keep, created_by=admin)[0]
    merge = IdentityMergeService()

    with pytest.raises(ValueError):
        merge.perform_merge(candidate=cand, by=admin)  # not approved yet

    merge.review(candidate=cand, decision="approve", by=admin)
    record = merge.perform_merge(candidate=cand, by=admin, surviving=keep)

    assert record.moved_counts.get("Condition") == 1
    assert Condition.objects.filter(patient=keep).count() == 1
    dup.refresh_from_db()
    assert dup.is_active is False
    cand.refresh_from_db()
    assert cand.status == PatientIdentityCandidate.Status.MERGED
    assert ReconciliationEvent.objects.get(kind="IDENTITY_CONFLICT").status == "RESOLVED"


def test_reject_marks_distinct_and_resolves_event(make_user):
    admin = make_user(Role.ADMIN)
    a = _patient("R1", "Ann", "Lee")
    _patient("R2", "Anne", "Lee")
    cand = IdentityResolver().scan_and_record(a, created_by=admin)[0]

    IdentityMergeService().review(candidate=cand, decision="distinct", by=admin, note="Different people")
    cand.refresh_from_db()
    assert cand.status == PatientIdentityCandidate.Status.CONFIRMED_DISTINCT
    assert ReconciliationEvent.objects.get(kind="IDENTITY_CONFLICT").status == "RESOLVED"


def test_identity_endpoints_require_permission(auth_client, make_user, make_doctor):
    # A doctor lacks patient.identity.manage.
    resp = auth_client(make_doctor().user).get("/api/v1/patients/identity/candidates/")
    assert resp.status_code == 403

    admin_client = auth_client(make_user(Role.ADMIN))
    assert admin_client.get("/api/v1/patients/identity/candidates/").status_code == 200
