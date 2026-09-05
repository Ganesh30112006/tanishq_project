from __future__ import annotations

import pytest

from apps.audit.models import AuditLog
from apps.common.enums import ClinicalDataState, Role
from apps.data_quality.models import DataQualityEvent
from apps.laboratories.models import LabOrder

pytestmark = pytest.mark.django_db


def test_lab_tech_order_result_validate_flow(auth_client, make_lab_tech, make_patient):
    tech = make_lab_tech()
    patient = make_patient()
    client = auth_client(tech.user)

    resp = client.post(
        "/api/v1/labs/orders/",
        {"patient_id": str(patient.public_id), "panel": "GLUCOSE"},
        format="json",
    )
    assert resp.status_code == 201
    order_id = resp.data["id"]

    resp = client.post(
        f"/api/v1/labs/orders/{order_id}/results/",
        {"analyte": "glucose", "state": ClinicalDataState.OBSERVED, "value": "5.4", "unit": "mmol/L"},
        format="json",
    )
    assert resp.status_code == 201
    assert float(resp.data["value_normalized"]) == 5.4
    assert resp.data["unit_normalized"] == "mmol/L"
    result_id = resp.data["id"]

    resp = client.post(f"/api/v1/labs/results/{result_id}/validate/", {"status": "PASSED"}, format="json")
    assert resp.status_code == 200

    # Data-quality assessment ran on entry (spec section 17).
    assert DataQualityEvent.objects.filter(subject_type="LabResult", subject_id=result_id).exists()
    assert AuditLog.objects.filter(action="lab_result.change").exists()


def test_doctor_reads_assigned_patient_orders_only(
    auth_client, make_lab_tech, make_patient, make_doctor, assign_patient
):
    tech = make_lab_tech()
    assigned = make_patient()
    unassigned = make_patient()
    LabOrder.objects.create(laboratory=tech.laboratory, patient=assigned, panel="GLUCOSE")
    LabOrder.objects.create(laboratory=tech.laboratory, patient=unassigned, panel="GLUCOSE")

    doctor = make_doctor()
    assign_patient(doctor, assigned)
    client = auth_client(doctor.user)

    listing = client.get("/api/v1/labs/orders/")
    assert listing.status_code == 200
    patient_ids = {row["patient_id"] for row in listing.data["results"]}
    assert patient_ids == {str(assigned.public_id)}


def test_patient_cannot_create_lab_order(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    resp = auth_client(alice).post(
        "/api/v1/labs/orders/",
        {"patient_id": str(patient.public_id), "panel": "GLUCOSE"},
        format="json",
    )
    assert resp.status_code == 403
