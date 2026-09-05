from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import AccountService
from apps.common.enums import Role
from apps.doctors.models import Doctor, DoctorPatientAssignment
from apps.doctors.services import AssignmentService
from apps.laboratories.models import Laboratory, LabOrder, LabTechnician
from apps.patients.models import Patient

account_service = AccountService()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(role: str | None = None, *, email: str | None = None, password: str = "correct horse battery") -> User:
        email = email or f"user-{uuid.uuid4().hex[:10]}@example.test"
        user = User.objects.create_user(email=email, password=password, full_name="Test User")
        if role:
            account_service.assign_role(user, role)
        return user

    return _make


@pytest.fixture
def auth_client(make_user):
    def _client(user: User | None = None, *, role: str | None = None) -> APIClient:
        user = user or make_user(role)
        raw = account_service.issue_local_token(user).raw
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        client.handler._caresense_user = user  # type: ignore[attr-defined]
        return client

    return _client


@pytest.fixture
def make_patient(db):
    def _make(*, user: User | None = None, mrn: str | None = None) -> Patient:
        return Patient.objects.create(
            mrn=mrn or f"MRN{uuid.uuid4().hex[:8].upper()}",
            given_name="Pat",
            family_name="Ient",
            user=user,
        )

    return _make


@pytest.fixture
def make_doctor(make_user):
    def _make(*, email: str | None = None) -> Doctor:
        user = make_user(Role.DOCTOR, email=email)
        return Doctor.objects.create(user=user, registration_number=f"REG{uuid.uuid4().hex[:8]}")

    return _make


@pytest.fixture
def assign_patient(db):
    service = AssignmentService()

    def _assign(doctor: Doctor, patient: Patient) -> DoctorPatientAssignment:
        return service.assign(doctor, patient)

    return _assign


@pytest.fixture
def make_lab_tech(make_user):
    def _make() -> LabTechnician:
        user = make_user(Role.LAB_TECHNICIAN)
        lab = Laboratory.objects.create(name="Central Lab", code=f"LAB{uuid.uuid4().hex[:6]}")
        return LabTechnician.objects.create(user=user, laboratory=lab)

    return _make


@pytest.fixture
def open_lab_order(db):
    def _make(lab_tech: LabTechnician, patient: Patient) -> LabOrder:
        return LabOrder.objects.create(
            laboratory=lab_tech.laboratory, patient=patient, panel="GLUCOSE"
        )

    return _make


@pytest.fixture
def make_measurement(db):
    """A model-readable vital in a trustworthy clinical state."""
    from django.utils import timezone

    from apps.common.enums import ClinicalDataState
    from apps.health.models import HealthMeasurement, MeasurementKind

    def _make(patient: Patient, *, kind: str = MeasurementKind.SYSTOLIC_BP, value="128"):
        return HealthMeasurement.objects.create(
            patient=patient,
            kind=kind,
            value_num=Decimal(value),
            unit="mmHg",
            state=ClinicalDataState.OBSERVED,
            observed_at=timezone.now(),
        )

    return _make
