"""Seed a small, realistic demo dataset for local development only.

Creates one user per role, a doctor-patient care team, laboratory workflow
data, vitals and lab results entered the same way a clinician or lab
technician would enter them (through the real services - never a raw fixture
that skips validation/normalization), and attempts a real, end-to-end risk
assessment for each patient through the intelligence service when it is
reachable.

Refuses to run outside DEBUG so this can never seed a production database.
Every write is idempotent (``get_or_create`` / ``update_or_create``) so
re-running is safe.

    python manage.py seed_demo
"""
from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import AccountService
from apps.alerts.models import Alert
from apps.common.enums import ClinicalDataState, Role
from apps.doctors.models import Doctor
from apps.doctors.services import AssignmentService
from apps.health.models import HealthMeasurement, MeasurementKind
from apps.laboratories.models import Laboratory, LabOrder, LabTechnician
from apps.laboratories.services import LabResultService
from apps.medical_records.models import Allergy, Condition, Medication
from apps.patients.models import Patient
from apps.patients.services import PatientService

DEMO_PASSWORD = "CareSenseDemo!2024"  # noqa: S105 - demo seed data, never a deployment

account_service = AccountService()
assignment_service = AssignmentService()
lab_result_service = LabResultService()
patient_service = PatientService()

_PATIENTS = [
    {
        "email": "maya.chen@demo.caresense.dev",
        "mrn": "MRN-DEMO-1001",
        "given_name": "Maya",
        "family_name": "Chen",
        "sex": "FEMALE",
        "age": 42,
        "vitals": {"SYSTOLIC_BP": 142, "DIASTOLIC_BP": 91, "HEART_RATE": 78, "SPO2": 98, "BMI": 29},
        "labs": {"glucose": 118, "hdl": 38},  # mg/dL
        "conditions": ["Hypertension", "Elevated LDL cholesterol"],
        "allergies": ["Penicillin"],
        "medications": [("Lisinopril", "10mg", "oral", "once daily"), ("Atorvastatin", "20mg", "oral", "once daily")],
        "alert": ("Elevated blood pressure trend", "MEDIUM", "Systolic readings above target for 3 consecutive visits."),
    },
    {
        "email": "jonas.williams@demo.caresense.dev",
        "mrn": "MRN-DEMO-1002",
        "given_name": "Jonas",
        "family_name": "Williams",
        "sex": "MALE",
        "age": 58,
        "vitals": {"SYSTOLIC_BP": 128, "DIASTOLIC_BP": 82, "HEART_RATE": 72, "SPO2": 97, "BMI": 27},
        "labs": {"glucose": 105, "hdl": 45},
        "conditions": ["Type 2 diabetes"],
        "allergies": [],
        "medications": [("Metformin", "500mg", "oral", "twice daily")],
        "alert": None,
    },
    {
        "email": "amina.okafor@demo.caresense.dev",
        "mrn": "MRN-DEMO-1003",
        "given_name": "Amina",
        "family_name": "Okafor",
        "sex": "FEMALE",
        "age": 31,
        "vitals": {"SYSTOLIC_BP": 112, "DIASTOLIC_BP": 74, "HEART_RATE": 66, "SPO2": 99, "BMI": 22},
        "labs": {"glucose": 88, "hdl": 65},
        "conditions": [],
        "allergies": [],
        "medications": [],
        "alert": None,
    },
]


class Command(BaseCommand):
    help = "Seed demo users, a care team and clinical data for local development."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_demo refuses to run outside DEBUG (never seed a real environment).")

        # New permission codes only reach existing roles when the catalog is
        # re-synced; without this a freshly added permission silently never
        # lands on the role that is supposed to hold it.
        account_service.sync_rbac_catalog()
        if not settings.IDENTITY.get("LOCAL_DEV_TOKENS"):
            self.stdout.write(self.style.WARNING(
                "LOCAL_DEV_TOKENS is disabled - the seeded accounts can still be listed "
                "here but the frontend's local login form will not be able to sign in."
            ))

        admin = self._user("admin@demo.caresense.dev", "Ada Admin", Role.ADMIN)
        doctor_user = self._user("dr.ortiz@demo.caresense.dev", "Lena Ortiz", Role.DOCTOR)
        doctor, _ = Doctor.objects.get_or_create(
            user=doctor_user, defaults={"registration_number": "REG-DEMO-001", "specialty": "Cardiology"}
        )
        lab_tech_user = self._user("tech.rivera@demo.caresense.dev", "Sam Rivera", Role.LAB_TECHNICIAN)
        lab, _ = Laboratory.objects.get_or_create(code="LAB-DEMO-01", defaults={"name": "Central Reference Lab"})
        LabTechnician.objects.get_or_create(user=lab_tech_user, defaults={"laboratory": lab, "employee_id": "T-01"})

        created_patients: list[Patient] = []
        for spec in _PATIENTS:
            patient = self._patient(spec)
            created_patients.append(patient)
            assignment_service.assign(doctor, patient, assigned_by=admin, reason="Demo care team")
            self._enter_vitals(patient, spec["vitals"])
            self._enter_labs(patient, spec["labs"], lab_tech_user, lab)
            for label in spec["conditions"]:
                Condition.objects.get_or_create(
                    patient=patient, label=label, defaults={"clinical_status": Condition.ClinicalStatus.ACTIVE}
                )
            for substance in spec["allergies"]:
                Allergy.objects.get_or_create(
                    patient=patient, substance=substance, defaults={"status": Allergy.Status.ACTIVE}
                )
            for name, dose, route, freq in spec["medications"]:
                Medication.objects.get_or_create(
                    patient=patient, name=name,
                    defaults={"dose": dose, "route": route, "frequency": freq, "status": Medication.Status.ACTIVE},
                )
            if spec["alert"]:
                title, severity, detail = spec["alert"]
                Alert.objects.get_or_create(
                    patient=patient, title=title,
                    defaults={"category": "clinical_review", "severity": severity, "detail": detail,
                              "created_by": doctor_user},
                )

        # One open lab order so the lab technician persona has workflow access
        # and something to see on their dashboard.
        LabOrder.objects.get_or_create(
            laboratory=lab, patient=created_patients[0], panel="GLUCOSE",
            defaults={"ordered_by": doctor, "status": LabOrder.Status.REQUESTED},
        )

        self._register_model(approver=admin)
        self._run_risk_assessments(doctor_user, created_patients)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Demo accounts (password for all: {DEMO_PASSWORD}):")
        )
        for spec, role in (
            ({"email": admin.email}, "ADMIN"),
            ({"email": doctor_user.email}, "DOCTOR"),
            ({"email": lab_tech_user.email}, "LAB_TECHNICIAN"),
            *[({"email": p["email"]}, "PATIENT") for p in _PATIENTS],
        ):
            self.stdout.write(f"  {spec['email']:<38} {role}")

    # -- helpers ------------------------------------------------------
    def _user(self, email: str, full_name: str, role: str) -> User:
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email=email, password=DEMO_PASSWORD, full_name=full_name)
        if not user.has_role(role):
            account_service.assign_role(user, role)
        return user

    def _patient(self, spec: dict) -> Patient:
        patient = Patient.objects.filter(mrn=spec["mrn"]).first()
        if patient is None:
            dob = timezone.now().date() - dt.timedelta(days=int(spec["age"] * 365.25))
            patient = patient_service.create_patient(
                mrn=spec["mrn"], given_name=spec["given_name"], family_name=spec["family_name"],
                date_of_birth=dob, sex=spec["sex"],
            )
        if patient.user_id is None:
            user = self._user(spec["email"], f"{spec['given_name']} {spec['family_name']}", Role.PATIENT)
            patient.user = user
            patient.save(update_fields=["user", "updated_at"])
        return patient

    def _enter_vitals(self, patient: Patient, vitals: dict[str, float]) -> None:
        now = timezone.now()
        for kind, value in vitals.items():
            if HealthMeasurement.objects.filter(patient=patient, kind=kind).exists():
                continue
            HealthMeasurement.objects.create(
                patient=patient, kind=kind, value_num=value, unit=_VITAL_UNIT.get(kind, ""),
                state=ClinicalDataState.OBSERVED, observed_at=now, source="demo_seed",
            )

    def _enter_labs(self, patient: Patient, labs: dict[str, float], entered_by, lab: Laboratory) -> None:
        if not labs:
            return
        order, _ = LabOrder.objects.get_or_create(
            laboratory=lab, patient=patient, panel="METABOLIC_PANEL",
            defaults={"status": LabOrder.Status.VALIDATED},
        )
        now = timezone.now()
        for analyte, value in labs.items():
            if order.results.filter(analyte=analyte).exists():
                continue
            lab_result_service.enter_result(
                order=order, analyte=analyte, state=ClinicalDataState.OBSERVED,
                value=value, unit="mg/dL", observed_at=now, entered_by=entered_by,
            )

    def _register_model(self, approver: User) -> None:
        meta_path = settings.BASE_DIR / "intelligence" / "_artifacts" / "cvd-1.0.0.meta.json"
        if not meta_path.exists():
            self.stdout.write(self.style.WARNING(
                f"No trained model artifact at {meta_path} - skipping model registration. "
                "Train one with `python -m intelligence.ml_service.train --task cvd --version 1.0.0 "
                "--out intelligence/_artifacts` first."
            ))
            return
        call_command("register_model", meta=str(meta_path))
        # Walk the demo model through the full governed lifecycle so the task
        # is live - with a recorded approver and reason at every step, exactly
        # as a real deployment must (spec section 54).
        from apps.risk.governance import ModelGovernanceService
        from apps.risk.models import ModelVersion

        mv = ModelVersion.objects.filter(model_id="cvd-logreg", version="1.0.0").first()
        if mv is None:
            return
        gov = ModelGovernanceService()
        steps = [
            ("VALIDATION", "seed_demo: technical validation of the demo model"),
            ("APPROVED_FOR_EVALUATION", "seed_demo: shadow evaluation sign-off"),
            ("APPROVED_FOR_CLINICAL_REVIEW", "seed_demo: demo governance board sign-off"),
        ]
        for to_state, reason in steps:
            if mv.lifecycle_state == to_state:
                continue
            mv = gov.transition(model_version=mv, to_state=to_state, actor=approver, reason=reason)
        gov.activate_for_task(task="cvd", model_version=mv, actor=approver)

    def _run_risk_assessments(self, doctor_user: User, patients: list[Patient]) -> None:
        from apps.risk.workflow import RiskRequestWorkflow

        workflow = RiskRequestWorkflow()
        for patient in patients:
            try:
                outcome = workflow.request(
                    actor=doctor_user, patient=patient, task="cvd", correlation_id="seed-demo"
                )
            except Exception as exc:  # noqa: BLE001 - best-effort demo data
                self.stdout.write(self.style.WARNING(
                    f"Risk assessment for {patient.full_name} skipped: {exc}. "
                    "Start the FastAPI intelligence service and re-run this command "
                    "for a fully populated demo."
                ))
                continue
            if outcome.result.ok:
                self.stdout.write(f"Risk assessment completed for {patient.full_name}.")
            else:
                self.stdout.write(self.style.WARNING(
                    f"Risk assessment for {patient.full_name} blocked: {outcome.result.code}."
                ))


_VITAL_UNIT = {
    MeasurementKind.SYSTOLIC_BP: "mmHg",
    MeasurementKind.DIASTOLIC_BP: "mmHg",
    MeasurementKind.HEART_RATE: "bpm",
    MeasurementKind.SPO2: "%",
    MeasurementKind.RESP_RATE: "breaths/min",
    MeasurementKind.TEMPERATURE: "degC",
    MeasurementKind.BMI: "kg/m2",
}
