"""Consultation booking, and the access it does (and does not) grant."""
from __future__ import annotations

import datetime as pydt

import pytest
from django.utils import timezone

from apps.appointments.models import Appointment, AvailabilitySlot
from apps.common.enums import Role
from apps.doctors.models import DoctorPatientAssignment

pytestmark = pytest.mark.django_db


def _future(hours: int = 24) -> pydt.datetime:
    return timezone.now() + pydt.timedelta(hours=hours)


@pytest.fixture
def slot(db):
    def _make(doctor, *, hours: int = 24) -> AvailabilitySlot:
        start = _future(hours)
        return AvailabilitySlot.objects.create(
            doctor=doctor, starts_at=start, ends_at=start + pydt.timedelta(minutes=30)
        )

    return _make


# --- publishing availability -------------------------------------------
def test_doctor_publishes_availability(auth_client, make_doctor):
    doctor = make_doctor()
    resp = auth_client(doctor.user).post(
        "/api/v1/appointments/availability/",
        {"starts_at": _future().isoformat(), "ends_at": (_future() + pydt.timedelta(minutes=30)).isoformat()},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert AvailabilitySlot.objects.filter(doctor=doctor).count() == 1


def test_patient_cannot_publish_availability(auth_client, make_user):
    resp = auth_client(make_user(Role.PATIENT)).post(
        "/api/v1/appointments/availability/",
        {"starts_at": _future().isoformat(), "ends_at": (_future() + pydt.timedelta(minutes=30)).isoformat()},
        format="json",
    )
    assert resp.status_code == 403
    assert not AvailabilitySlot.objects.exists()


def test_availability_must_be_in_the_future(auth_client, make_doctor):
    past = timezone.now() - pydt.timedelta(hours=2)
    resp = auth_client(make_doctor().user).post(
        "/api/v1/appointments/availability/",
        {"starts_at": past.isoformat(), "ends_at": (past + pydt.timedelta(minutes=30)).isoformat()},
        format="json",
    )
    assert resp.status_code == 400


# --- booking -----------------------------------------------------------
def test_booking_is_what_grants_the_clinician_access(
    auth_client, make_doctor, make_user, make_patient, slot
):
    doctor = make_doctor()
    patient_user = make_user(Role.PATIENT)
    patient = make_patient(user=patient_user, mrn="MRN-APPT-1")
    open_slot = slot(doctor)

    # The clinician cannot see this record before any relationship exists.
    before = auth_client(doctor.user).get(f"/api/v1/patients/{patient.public_id}/")
    assert before.status_code in (403, 404)

    booked = auth_client(patient_user).post(
        "/api/v1/appointments/",
        {"slot_id": str(open_slot.public_id), "reason": "Worried about my cholesterol result"},
        format="json",
    )
    assert booked.status_code == 201, booked.data
    assert booked.data["status"] == "REQUESTED"

    # A request alone does not hand over the record.
    still_denied = auth_client(doctor.user).get(f"/api/v1/patients/{patient.public_id}/")
    assert still_denied.status_code in (403, 404)

    confirmed = auth_client(doctor.user).post(
        f"/api/v1/appointments/{booked.data['id']}/confirm/", {}, format="json"
    )
    assert confirmed.status_code == 200, confirmed.data
    assert DoctorPatientAssignment.objects.filter(
        doctor=doctor, patient=patient, status=DoctorPatientAssignment.Status.ACTIVE
    ).exists()
    after = auth_client(doctor.user).get(f"/api/v1/patients/{patient.public_id}/")
    assert after.status_code == 200


def test_a_slot_cannot_be_double_booked(auth_client, make_doctor, make_user, make_patient, slot):
    doctor = make_doctor()
    open_slot = slot(doctor)
    first_user = make_user(Role.PATIENT)
    make_patient(user=first_user, mrn="MRN-APPT-2")
    second_user = make_user(Role.PATIENT)
    make_patient(user=second_user, mrn="MRN-APPT-3")

    first = auth_client(first_user).post(
        "/api/v1/appointments/", {"slot_id": str(open_slot.public_id)}, format="json"
    )
    assert first.status_code == 201
    second = auth_client(second_user).post(
        "/api/v1/appointments/", {"slot_id": str(open_slot.public_id)}, format="json"
    )
    assert second.status_code == 400
    assert Appointment.objects.filter(slot=open_slot).count() == 1


def test_booked_slot_leaves_the_public_directory(auth_client, make_doctor, make_user, make_patient, slot):
    doctor = make_doctor()
    open_slot = slot(doctor)
    other = make_user(Role.PATIENT)
    make_patient(user=other, mrn="MRN-APPT-4")
    booker = make_user(Role.PATIENT)
    make_patient(user=booker, mrn="MRN-APPT-5")

    listed = auth_client(other).get("/api/v1/appointments/availability/")
    assert any(row["id"] == str(open_slot.public_id) for row in listed.data["results"])

    auth_client(booker).post(
        "/api/v1/appointments/", {"slot_id": str(open_slot.public_id)}, format="json"
    )
    after = auth_client(other).get("/api/v1/appointments/availability/")
    assert not any(row["id"] == str(open_slot.public_id) for row in after.data["results"])


def test_patient_without_a_record_cannot_book(auth_client, make_doctor, make_user, slot):
    open_slot = slot(make_doctor())
    resp = auth_client(make_user(Role.PATIENT)).post(
        "/api/v1/appointments/", {"slot_id": str(open_slot.public_id)}, format="json"
    )
    assert resp.status_code == 403


# --- scoping -----------------------------------------------------------
def test_each_side_sees_only_their_own_appointments(
    auth_client, make_doctor, make_user, make_patient, slot
):
    doctor = make_doctor()
    mine_user = make_user(Role.PATIENT)
    make_patient(user=mine_user, mrn="MRN-APPT-6")
    theirs_user = make_user(Role.PATIENT)
    make_patient(user=theirs_user, mrn="MRN-APPT-7")

    mine = auth_client(mine_user).post(
        "/api/v1/appointments/", {"slot_id": str(slot(doctor).public_id)}, format="json"
    )
    theirs = auth_client(theirs_user).post(
        "/api/v1/appointments/", {"slot_id": str(slot(doctor, hours=48).public_id)}, format="json"
    )
    assert mine.status_code == 201 and theirs.status_code == 201

    listed = auth_client(mine_user).get("/api/v1/appointments/")
    ids = [row["id"] for row in listed.data["results"]]
    assert mine.data["id"] in ids
    assert theirs.data["id"] not in ids

    # The clinician on both sees both.
    doctor_view = auth_client(doctor.user).get("/api/v1/appointments/")
    doctor_ids = [row["id"] for row in doctor_view.data["results"]]
    assert mine.data["id"] in doctor_ids and theirs.data["id"] in doctor_ids


def test_another_clinician_cannot_confirm_someone_elses_appointment(
    auth_client, make_doctor, make_user, make_patient, slot
):
    doctor = make_doctor()
    intruder = make_doctor()
    patient_user = make_user(Role.PATIENT)
    make_patient(user=patient_user, mrn="MRN-APPT-8")
    booked = auth_client(patient_user).post(
        "/api/v1/appointments/", {"slot_id": str(slot(doctor).public_id)}, format="json"
    )
    resp = auth_client(intruder.user).post(
        f"/api/v1/appointments/{booked.data['id']}/confirm/", {}, format="json"
    )
    assert resp.status_code in (403, 404)
    assert Appointment.objects.get(public_id=booked.data["id"]).status == "REQUESTED"


def test_patient_cannot_confirm_their_own_booking(
    auth_client, make_doctor, make_user, make_patient, slot
):
    doctor = make_doctor()
    patient_user = make_user(Role.PATIENT)
    make_patient(user=patient_user, mrn="MRN-APPT-9")
    booked = auth_client(patient_user).post(
        "/api/v1/appointments/", {"slot_id": str(slot(doctor).public_id)}, format="json"
    )
    resp = auth_client(patient_user).post(
        f"/api/v1/appointments/{booked.data['id']}/confirm/", {}, format="json"
    )
    assert resp.status_code == 403
    assert Appointment.objects.get(public_id=booked.data["id"]).status == "REQUESTED"


def test_patient_may_cancel_and_the_slot_frees_up(
    auth_client, make_doctor, make_user, make_patient, slot
):
    doctor = make_doctor()
    patient_user = make_user(Role.PATIENT)
    make_patient(user=patient_user, mrn="MRN-APPT-10")
    open_slot = slot(doctor)
    booked = auth_client(patient_user).post(
        "/api/v1/appointments/", {"slot_id": str(open_slot.public_id)}, format="json"
    )
    cancelled = auth_client(patient_user).post(
        f"/api/v1/appointments/{booked.data['id']}/cancel/",
        {"reason": "No longer needed"},
        format="json",
    )
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == "CANCELLED"

    # The time is bookable again.
    other = make_user(Role.PATIENT)
    make_patient(user=other, mrn="MRN-APPT-11")
    rebooked = auth_client(other).post(
        "/api/v1/appointments/", {"slot_id": str(open_slot.public_id)}, format="json"
    )
    assert rebooked.status_code == 201


def test_cannot_attach_someone_elses_analysis_to_a_booking(
    auth_client, make_doctor, make_user, make_patient, slot
):
    from apps.risk.models import RiskAssessment

    doctor = make_doctor()
    booker = make_user(Role.PATIENT)
    make_patient(user=booker, mrn="MRN-APPT-12")
    victim = make_patient(mrn="MRN-APPT-13")
    foreign = RiskAssessment.objects.create(
        patient=victim, task="cvd", status=RiskAssessment.Status.BLOCKED,
        outcome_code="INSUFFICIENT_DATA", input_snapshot={},
    )
    resp = auth_client(booker).post(
        "/api/v1/appointments/",
        {"slot_id": str(slot(doctor).public_id), "assessment_id": str(foreign.public_id)},
        format="json",
    )
    assert resp.status_code == 404
    assert not Appointment.objects.exists()
