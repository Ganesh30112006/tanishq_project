"""Built-in resource policies.

Registered with the engine in :meth:`AuthzConfig.ready`. Each policy is small
and returns an explicit :class:`Decision` with a human-readable reason so
denials are traceable in the audit log.
"""
from __future__ import annotations

from apps.authz.engine import AccessRequest, Action, Decision, engine
from apps.authz.relationships import (
    is_assigned_doctor,
    is_self,
    lab_tech_has_workflow,
)
from apps.common.enums import Role

# Resource classes that belong to the laboratory workflow.
LAB_RESOURCE_TYPES = {
    "LabOrder",
    "LabResult",
    "LabResultValidation",
    "Report",
    "MissingDataTask",
    "HealthMeasurement",
}

# Doctor-authored resource classes.
DOCTOR_WRITABLE_TYPES = {
    "Appointment",
    "ClinicalNote",
    "Alert",
    "MissingDataTask",
    "RiskAssessment",
    "Condition",
    "Medication",
    "Allergy",
    "Symptom",
    "HealthMeasurement",
    "MedicalHistory",
}

READ_ACTIONS = {Action.READ}
LAB_WORKFLOW_ACTIONS = {Action.READ, Action.CREATE, Action.UPDATE, Action.VALIDATE, Action.PROCESS}


# Attributes through which a resource may reach its owning patient. Some
# clinical rows link to the patient only transitively (a lab result via its
# order, a report test via its report, and so on).
_PATIENT_PATHS = ("patient", "order", "report", "assessment", "lab_result", "event")


def resolve_patient(resource, *, _depth: int = 0):
    from apps.patients.models import Patient

    if isinstance(resource, Patient):
        return resource
    if _depth > 3:
        return None
    for attr in _PATIENT_PATHS:
        if not hasattr(resource, attr):
            continue
        related = getattr(resource, attr, None)
        if related is None:
            continue
        found = resolve_patient(related, _depth=_depth + 1)
        if found is not None:
            return found
    patient_id = getattr(resource, "patient_id", None)
    if patient_id is not None:
        return Patient.objects.filter(pk=patient_id).first()
    return None


class PatientScopedPolicy:
    """Covers ``Patient`` and any resource that resolves to a single patient."""

    name = "patient-scoped"

    def handles(self, resource) -> bool:
        from apps.patients.models import Patient

        if isinstance(resource, Patient):
            return True
        return any(hasattr(resource, attr) for attr in (*_PATIENT_PATHS, "patient_id"))

    def decide(self, request: AccessRequest) -> Decision:
        actor, action = request.actor, request.action
        patient = resolve_patient(request.resource)
        if patient is None:
            return Decision.deny(self.name, "resource is not linked to a patient")

        resource_type = type(request.resource).__name__

        if getattr(actor, "is_superuser", False):
            return Decision.allow(self.name, "superuser")

        if actor.has_role(Role.ADMIN):
            if action in READ_ACTIONS:
                return Decision.allow(self.name, "admin read")
            return Decision.deny(self.name, "admin may not write clinical resources")

        if actor.has_role(Role.PATIENT):
            if not is_self(actor, patient):
                return Decision.deny(self.name, "patients may access only their own resources")
            if action in READ_ACTIONS:
                return Decision.allow(self.name, "patient self read")
            if action == Action.CREATE and resource_type == "Report":
                return Decision.allow(self.name, "patient uploads own report")
            # A person may ask what their own recorded results indicate. The
            # answer is a calibrated risk band with its limitations attached -
            # the engine still blocks rather than guess (spec sections 15, 58).
            if action == Action.REQUEST_RISK:
                return Decision.allow(self.name, "patient requests own risk analysis")
            if action == Action.CREATE and resource_type == "Appointment":
                return Decision.allow(self.name, "patient books own consultation")
            return Decision.deny(self.name, "patient not permitted this action")

        if actor.has_role(Role.DOCTOR):
            if not is_assigned_doctor(actor, patient):
                return Decision.deny(self.name, "doctor is not assigned to this patient")
            if action in READ_ACTIONS:
                return Decision.allow(self.name, "assigned doctor read")
            if action in {Action.REQUEST_RISK, Action.USE_AI}:
                return Decision.allow(self.name, "assigned doctor clinical action")
            if action in {Action.CREATE, Action.UPDATE} and resource_type in DOCTOR_WRITABLE_TYPES:
                return Decision.allow(self.name, "assigned doctor authoring")
            return Decision.deny(self.name, "doctor not permitted this action")

        if actor.has_role(Role.LAB_TECHNICIAN):
            if not lab_tech_has_workflow(actor, patient):
                return Decision.deny(self.name, "no lab workflow links technician to patient")
            from apps.patients.models import Patient

            if isinstance(request.resource, Patient):
                if action in READ_ACTIONS:
                    # Minimum-necessary identity only; enforced by the serializer.
                    return Decision.allow(self.name, "lab minimal identity read")
                return Decision.deny(self.name, "lab may not modify patient identity")
            if resource_type in LAB_RESOURCE_TYPES and action in LAB_WORKFLOW_ACTIONS:
                return Decision.allow(self.name, "lab workflow action")
            return Decision.deny(self.name, "outside lab workflow scope")

        return Decision.deny(self.name, "no applicable role relationship")


class SelfOwnedPolicy:
    """Resources owned directly by a user (notifications, own tokens)."""

    name = "self-owned"
    OWNED_TYPES = {"Notification", "AccessToken"}

    def handles(self, resource) -> bool:
        return type(resource).__name__ in self.OWNED_TYPES

    def decide(self, request: AccessRequest) -> Decision:
        actor = request.actor
        owner_id = getattr(request.resource, "user_id", getattr(request.resource, "recipient_id", None))
        if getattr(actor, "is_superuser", False):
            return Decision.allow(self.name, "superuser")
        if owner_id == actor.pk:
            return Decision.allow(self.name, "owner")
        return Decision.deny(self.name, "not the owner")


def _register() -> None:
    engine.clear()
    engine.register(PatientScopedPolicy())
    engine.register(SelfOwnedPolicy())


_register()
