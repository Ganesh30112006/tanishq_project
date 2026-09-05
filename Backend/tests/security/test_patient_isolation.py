"""Non-negotiable security tests (spec section 54)."""
from __future__ import annotations

import pytest

from apps.common.enums import Role

pytestmark = pytest.mark.django_db


def test_patient_a_cannot_read_patient_b(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    bob = make_user(Role.PATIENT)
    make_patient(user=alice)
    bob_patient = make_patient(user=bob)

    client = auth_client(alice)
    # IDOR attempt: Patient A requests Patient B by id.
    resp = client.get(f"/api/v1/patients/{bob_patient.public_id}/")
    assert resp.status_code in (403, 404)

    listing = client.get("/api/v1/patients/")
    ids = [row["id"] for row in listing.data["results"]]
    assert str(bob_patient.public_id) not in ids


def test_doctor_cannot_read_unassigned_patient(auth_client, make_doctor, make_patient, assign_patient):
    doctor = make_doctor()
    assigned = make_patient()
    unassigned = make_patient()
    assign_patient(doctor, assigned)

    client = auth_client(doctor.user)
    assert client.get(f"/api/v1/patients/{assigned.public_id}/").status_code == 200
    assert client.get(f"/api/v1/patients/{unassigned.public_id}/").status_code in (403, 404)


def test_patient_cannot_hit_admin_user_endpoint(auth_client, make_user):
    client = auth_client(make_user(Role.PATIENT))
    resp = client.get("/api/v1/users/")
    assert resp.status_code == 403
    assert resp.data["error"]["code"] == "ACCESS_DENIED"


def test_client_supplied_role_claim_does_not_change_authorization(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    other = make_patient()
    client = auth_client(alice)
    # Attempt to assert a role via headers / body - must be ignored.
    resp = client.get(
        f"/api/v1/patients/{other.public_id}/",
        HTTP_X_ROLE="ADMIN",
        data={"role": "ADMIN"},
    )
    assert resp.status_code in (403, 404)


def test_lab_tech_sees_only_minimal_identity_and_only_with_workflow(
    auth_client, make_lab_tech, make_patient, open_lab_order
):
    tech = make_lab_tech()
    linked = make_patient()
    open_lab_order(tech, linked)
    unlinked = make_patient()

    client = auth_client(tech.user)
    ok = client.get(f"/api/v1/patients/{linked.public_id}/")
    assert ok.status_code == 200
    assert "phone" not in ok.data  # minimal identity serializer

    assert client.get(f"/api/v1/patients/{unlinked.public_id}/").status_code in (403, 404)
