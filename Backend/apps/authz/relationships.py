"""Relationship resolvers.

These answer the RELATIONSHIP part of the authorization tuple. They are the
single place that knows how a user is connected to a patient, so policies and
queryset-scoping stay consistent.
"""
from __future__ import annotations

from django.db.models import QuerySet

from apps.common.enums import Role


def patient_for_user(user) -> "object | None":
    from apps.patients.models import Patient

    return Patient.objects.filter(user_id=user.pk).first()


def is_self(user, patient) -> bool:
    return patient is not None and patient.user_id == user.pk


def is_assigned_doctor(user, patient) -> bool:
    from apps.doctors.models import DoctorPatientAssignment

    if patient is None:
        return False
    return DoctorPatientAssignment.objects.filter(
        doctor__user_id=user.pk,
        patient_id=patient.pk,
        status=DoctorPatientAssignment.Status.ACTIVE,
    ).exists()


def lab_tech_has_workflow(user, patient) -> bool:
    """True when the technician's laboratory has an open order/task for the
    patient - the minimum linkage that authorizes lab workflow access."""
    from apps.laboratories.models import LabOrder, LabTechnician

    if patient is None:
        return False
    lab_ids = list(
        LabTechnician.objects.filter(user_id=user.pk, is_active=True).values_list(
            "laboratory_id", flat=True
        )
    )
    if not lab_ids:
        return False
    return LabOrder.objects.filter(
        laboratory_id__in=lab_ids,
        patient_id=patient.pk,
        status__in=LabOrder.OPEN_STATUSES,
    ).exists()


# --------------------------------------------------------------------------
# Queryset scoping - authorize BEFORE returning data (spec section 6)
# --------------------------------------------------------------------------
def visible_patient_queryset(user) -> QuerySet:
    from apps.doctors.models import DoctorPatientAssignment
    from apps.laboratories.models import LabOrder, LabTechnician
    from apps.patients.models import Patient

    if getattr(user, "is_superuser", False) or user.has_role(Role.ADMIN):
        # An administrator manages accounts, staff, identity and audit records.
        # The permission catalogue gives them no clinical read permission at
        # all, so the relationship layer must not quietly hand them what the
        # permission layer denies: scoping every clinical viewset through "all
        # patients" gave admins alerts, lab results and risk assessments for
        # people they cannot even list. Administrative surfaces that genuinely
        # need a patient row (identity merges, linking an account to a record)
        # look it up directly and are audited; they do not come through here.
        return Patient.objects.none()

    if user.has_role(Role.DOCTOR):
        assigned = DoctorPatientAssignment.objects.filter(
            doctor__user_id=user.pk, status=DoctorPatientAssignment.Status.ACTIVE
        ).values_list("patient_id", flat=True)
        return Patient.objects.filter(pk__in=assigned)

    if user.has_role(Role.LAB_TECHNICIAN):
        lab_ids = LabTechnician.objects.filter(user_id=user.pk, is_active=True).values_list(
            "laboratory_id", flat=True
        )
        patient_ids = LabOrder.objects.filter(
            laboratory_id__in=lab_ids, status__in=LabOrder.OPEN_STATUSES
        ).values_list("patient_id", flat=True)
        return Patient.objects.filter(pk__in=patient_ids)

    if user.has_role(Role.PATIENT):
        return Patient.objects.filter(user_id=user.pk)

    return Patient.objects.none()


def resolve_visible_patient(user, public_id):
    """Return the patient the caller is allowed to see for ``public_id``, or
    ``None``. Resolving through the visible queryset means an unauthorized id
    is indistinguishable from a missing one (no IDOR oracle)."""
    return visible_patient_queryset(user).filter(public_id=public_id).first()
