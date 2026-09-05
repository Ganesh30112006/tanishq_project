"""What each role may reach, checked at the boundary rather than in the UI.

Hiding a page in the frontend is presentation. These assert the server refuses,
and they exist because the relationship layer used to contradict the permission
layer: an administrator holds no clinical read permission, yet every clinical
viewset scoped itself through "all patients" for the ADMIN role, handing them
alerts, lab results and risk assessments for people they cannot even list.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from apps.ai.models import AiInteraction
from apps.alerts.models import Alert
from apps.common.enums import Role
from apps.risk.models import RiskAssessment

pytestmark = pytest.mark.django_db


@pytest.fixture
def populated(make_user, make_patient, make_doctor, assign_patient, open_lab_order, make_lab_tech):
    """One patient with clinical content, an assigned doctor, and an open order."""
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    doctor = make_doctor()
    assign_patient(doctor, patient)
    lab_tech = make_lab_tech()
    open_lab_order(lab_tech, patient)

    RiskAssessment.objects.create(
        patient=patient, requested_by=doctor.user, task="cvd",
        status=RiskAssessment.Status.COMPLETED, outcome_code="OK",
        calibrated_score=Decimal("0.80"), input_snapshot={},
    )
    Alert.objects.create(
        patient=patient, category="clinical_review", severity=Alert.Severity.MEDIUM,
        title="Elevated blood pressure trend",
        detail="Systolic readings above target for 3 consecutive visits.",
    )
    AiInteraction.objects.create(
        patient=patient, kind="HISTORY_SUMMARY", status=AiInteraction.Status.COMPLETED,
        prompt_summary="Summarise this patient's picture.",
        output_text="OBSERVED DATA:\n- hdl: 0.98 mmol/L",
    )
    return {"patient": patient, "alice": alice, "doctor": doctor, "lab_tech": lab_tech}


# --- the administrator --------------------------------------------------
CLINICAL_LISTS = [
    "/api/v1/alerts/",
    "/api/v1/risk/assessments/",
    "/api/v1/labs/orders/",
    "/api/v1/labs/results/",
    "/api/v1/ai/interactions/",
    "/api/v1/health/measurements/",
    "/api/v1/records/conditions/",
    "/api/v1/records/medications/",
]


@pytest.mark.parametrize("path", CLINICAL_LISTS)
def test_an_administrator_reads_no_clinical_row(auth_client, make_user, populated, path):
    """Managing accounts must never carry the ability to read inside records."""
    admin = make_user(Role.ADMIN)
    resp = auth_client(admin).get(path)
    assert resp.status_code in (200, 403), resp.status_code
    if resp.status_code == 200:
        assert resp.data["count"] == 0, f"{path} leaked {resp.data['count']} row(s) to an admin"


def test_an_administrator_cannot_open_one_assessment(auth_client, make_user, populated):
    admin = make_user(Role.ADMIN)
    row = RiskAssessment.objects.get(patient=populated["patient"])
    resp = auth_client(admin).get(f"/api/v1/risk/assessments/{row.public_id}/")
    assert resp.status_code in (403, 404)


def test_an_administrator_still_sees_the_chase_up_queue(auth_client, make_user, populated):
    """Oversight of an operational queue survives the clinical lockdown."""
    admin = make_user(Role.ADMIN)
    resp = auth_client(admin).get("/api/v1/notifications/tasks/")
    assert resp.status_code == 200


# --- the laboratory technician ------------------------------------------
def test_a_lab_technician_gets_identity_only_not_the_record(auth_client, populated):
    """An open order puts a patient in the technician's scope for labelling a
    sample - not for reading the clinical picture."""
    tech = populated["lab_tech"].user
    resp = auth_client(tech).get("/api/v1/patients/")
    assert resp.status_code == 200
    assert resp.data["count"] == 1
    row = resp.data["results"][0]
    assert "conditions" not in row and "risk_score" not in row


def test_a_lab_technician_cannot_read_clinical_alerts(auth_client, populated):
    """An alert states a clinical finding, not a sample-labelling detail."""
    tech = populated["lab_tech"].user
    resp = auth_client(tech).get("/api/v1/alerts/")
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert resp.data["count"] == 0


def test_a_lab_technician_cannot_read_ai_summaries(auth_client, populated):
    """An interaction restates the record, so reading one is reading the record."""
    tech = populated["lab_tech"].user
    resp = auth_client(tech).get("/api/v1/ai/interactions/")
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert resp.data["count"] == 0


# --- the people who should reach it -------------------------------------
def test_the_assigned_doctor_still_reads_everything_they_need(auth_client, populated):
    doctor = populated["doctor"].user
    for path in ("/api/v1/alerts/", "/api/v1/risk/assessments/", "/api/v1/ai/interactions/"):
        resp = auth_client(doctor).get(path)
        assert resp.status_code == 200, path
        assert resp.data["count"] >= 1, f"{path} hid a row from the assigned doctor"


def test_the_patient_still_reads_their_own(auth_client, populated):
    alice = populated["alice"]
    for path in ("/api/v1/alerts/", "/api/v1/risk/assessments/", "/api/v1/ai/interactions/"):
        resp = auth_client(alice).get(path)
        assert resp.status_code == 200, path
        assert resp.data["count"] >= 1, f"{path} hid the patient's own row"


# --- finding a record is not reading it ---------------------------------
def test_an_administrator_can_find_a_record_but_not_read_inside_it(
    auth_client, make_user, populated
):
    """Linking a login to a record needs the record found, not opened."""
    admin = make_user(Role.ADMIN)
    resp = auth_client(admin).get("/api/v1/patients/")
    assert resp.status_code == 200
    assert resp.data["count"] >= 1, "an admin cannot link an account they cannot find"

    row = resp.data["results"][0]
    assert set(row) == {
        "id", "mrn", "given_name", "family_name", "full_name",
        "date_of_birth", "age", "sex",
    }
    for clinical in ("conditions", "medications", "risk_score", "risk_level", "latest_alert"):
        assert clinical not in row, f"identity search leaked {clinical}"


def test_an_administrator_opening_one_record_still_gets_identity_only(
    auth_client, make_user, populated
):
    admin = make_user(Role.ADMIN)
    patient = populated["patient"]
    resp = auth_client(admin).get(f"/api/v1/patients/{patient.public_id}/")
    assert resp.status_code == 200
    assert "conditions" not in resp.data and "risk_score" not in resp.data


def test_a_lab_technician_sees_only_their_own_laboratorys_reports(
    auth_client, populated, make_user
):
    """An open order is not a key to the patient's whole document folder."""
    from apps.reports.models import Report

    patient = populated["patient"]
    tech = populated["lab_tech"]

    # Something the patient uploaded themselves - a discharge summary, say.
    Report.objects.create(
        patient=patient, uploaded_by=populated["alice"],
        original_filename="discharge-summary.pdf", source_file="reports/x.pdf",
    )
    # And something the technician's own laboratory produced.
    Report.objects.create(
        patient=patient, uploaded_by=tech.user,
        original_filename="glucose-panel.pdf", source_file="reports/y.pdf",
    )

    resp = auth_client(tech.user).get("/api/v1/reports/")
    assert resp.status_code == 200
    titles = {row["title"] for row in resp.data["results"]}
    assert "glucose-panel.pdf" in titles, "the lab lost sight of its own work"
    assert "discharge-summary.pdf" not in titles, "the lab can read the patient's other documents"

    # The patient and their doctor still see both.
    for user in (populated["alice"], populated["doctor"].user):
        resp = auth_client(user).get("/api/v1/reports/")
        assert {row["title"] for row in resp.data["results"]} >= {
            "glucose-panel.pdf", "discharge-summary.pdf",
        }
