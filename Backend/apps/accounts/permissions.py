"""Centralized permission registry and evaluation.

Authorization is NEVER expressed as scattered ``if user.role == "doctor"``
checks (spec section 5). Every capability is a named permission here; roles
map to permissions in the database; code asks the :class:`PermissionResolver`.

Resource-level rules (is this doctor assigned to *this* patient?) live in
``apps.authz`` - this module answers only "may this role do this kind of
thing at all?".
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.common.enums import Role
from apps.common.errors import AccessDenied

# --------------------------------------------------------------------------
# Canonical permission codes
# --------------------------------------------------------------------------
# Accounts / administration
USERS_MANAGE = "users.manage"
ROLES_MANAGE = "roles.manage"
PERMISSIONS_MANAGE = "permissions.manage"
SYSTEM_CONFIG_MANAGE = "system.config.manage"
MODEL_METADATA_MANAGE = "model.metadata.manage"
AUDIT_READ = "audit.read"
PATIENT_IDENTITY_MANAGE = "patient.identity.manage"
RECONCILIATION_MANAGE = "reconciliation.manage"
# Governs the clinical prediction-model lifecycle (draft -> validation ->
# approval -> retirement). Distinct from MODEL_METADATA_MANAGE, which only
# edits descriptive metadata and can never move a model toward clinical use.
MODEL_GOVERNANCE_MANAGE = "model.governance.manage"
# Onboard and maintain clinical staff: doctor / lab-technician profiles and the
# doctor-patient assignments that grant clinical access. Separate from
# USERS_MANAGE (which owns the login account) so account administration and
# care-relationship administration can be delegated independently.
STAFF_MANAGE = "staff.manage"

# Register a new patient record. Held by admins and by clinicians, who
# routinely admit patients; it creates an identity, never clinical findings.
PATIENT_REGISTER = "patient.register"

# Patient-facing (self scope)
PATIENT_READ_OWN = "patient.read.own"
RECORD_READ_OWN = "record.read.own"
REPORT_READ_OWN = "report.read.own"
REPORT_UPLOAD_OWN = "report.upload.own"
RISK_READ_OWN = "risk.read.own"
# A patient may run the analysis on their own record. This is the consumer
# path: the person supplies their own results and asks what they mean. The
# output is still a calibrated risk band with limitations, never a diagnosis.
RISK_REQUEST_OWN = "risk.request.own"
# Book, reschedule and cancel their own consultations.
APPOINTMENT_BOOK = "appointment.book"
NOTIFICATION_READ_OWN = "notification.read.own"

# Doctor
PATIENT_READ_ASSIGNED = "patient.read.assigned"
RECORD_READ_ASSIGNED = "record.read.assigned"
REPORT_READ_ASSIGNED = "report.read.assigned"
RISK_READ_ASSIGNED = "risk.read.assigned"
RISK_REQUEST = "risk.request"
# Record a clinical review decision on a model output. The assessment stays a
# non-finalized "decision support" artifact until a clinician reviews it.
RISK_REVIEW = "risk.review"
CLINICAL_NOTE_CREATE = "clinical_note.create"
ALERT_MANAGE = "alert.manage"
MISSING_DATA_REQUEST = "missing_data.request"
AI_USE = "ai.use"
# Publish availability and accept / decline / complete consultations.
APPOINTMENT_MANAGE = "appointment.manage"

# Lab technician
LAB_WORKFLOW_ACCESS = "lab.workflow.access"
LAB_PATIENT_IDENTITY_READ_MIN = "lab.patient_identity.read.min"
LAB_REPORT_UPLOAD = "lab.report.upload"
LAB_RESULT_ENTER = "lab.result.enter"
LAB_RESULT_VALIDATE = "lab.result.validate"
LAB_TASK_PROCESS = "lab.task.process"
LAB_MISSING_DATA_RESOLVE = "lab.missing_data.resolve"


PERMISSION_CATALOG: dict[str, tuple[str, str]] = {
    USERS_MANAGE: ("admin", "Create, update and deactivate user accounts"),
    ROLES_MANAGE: ("admin", "Manage roles"),
    PERMISSIONS_MANAGE: ("admin", "Manage permissions and role-permission mapping"),
    SYSTEM_CONFIG_MANAGE: ("admin", "Manage system configuration"),
    MODEL_METADATA_MANAGE: ("admin", "Manage model registry metadata where permitted"),
    MODEL_GOVERNANCE_MANAGE: ("admin", "Move clinical models through their governed lifecycle"),
    AUDIT_READ: ("admin", "Read audit records"),
    PATIENT_IDENTITY_MANAGE: ("admin", "Review and merge potential duplicate patient identities"),
    STAFF_MANAGE: ("admin", "Onboard clinical staff and manage doctor-patient assignments"),
    PATIENT_REGISTER: ("admin", "Register a new patient record"),
    RECONCILIATION_MANAGE: ("admin", "Review and resolve reconciliation events"),
    PATIENT_READ_OWN: ("patient", "View own patient profile"),
    RECORD_READ_OWN: ("patient", "View own medical records"),
    REPORT_READ_OWN: ("patient", "View own reports"),
    REPORT_UPLOAD_OWN: ("patient", "Upload permitted reports for self"),
    RISK_READ_OWN: ("patient", "View own risk assessments"),
    RISK_REQUEST_OWN: ("patient", "Run a risk analysis on their own record"),
    APPOINTMENT_BOOK: ("patient", "Book and cancel their own consultations"),
    NOTIFICATION_READ_OWN: ("patient", "View own notifications"),
    PATIENT_READ_ASSIGNED: ("doctor", "View assigned patients"),
    RECORD_READ_ASSIGNED: ("doctor", "View authorized records of assigned patients"),
    REPORT_READ_ASSIGNED: ("doctor", "View reports of assigned patients"),
    RISK_READ_ASSIGNED: ("doctor", "View risk assessments of assigned patients"),
    RISK_REQUEST: ("doctor", "Request a risk analysis"),
    RISK_REVIEW: ("doctor", "Record a clinical review decision on a model output"),
    CLINICAL_NOTE_CREATE: ("doctor", "Create authorized clinical notes"),
    ALERT_MANAGE: ("doctor", "Manage relevant alerts"),
    MISSING_DATA_REQUEST: ("doctor", "Request missing information"),
    AI_USE: ("doctor", "Use authorized AI functionality"),
    APPOINTMENT_MANAGE: ("doctor", "Publish availability and manage consultations"),
    LAB_WORKFLOW_ACCESS: ("lab", "Access authorized lab workflow"),
    LAB_PATIENT_IDENTITY_READ_MIN: ("lab", "View minimum required patient identity info"),
    LAB_REPORT_UPLOAD: ("lab", "Upload laboratory reports"),
    LAB_RESULT_ENTER: ("lab", "Enter laboratory results"),
    LAB_RESULT_VALIDATE: ("lab", "Validate laboratory results"),
    LAB_TASK_PROCESS: ("lab", "Process report tasks"),
    LAB_MISSING_DATA_RESOLVE: ("lab", "Resolve laboratory-related missing data"),
}


DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    Role.PATIENT: [
        PATIENT_READ_OWN,
        RECORD_READ_OWN,
        REPORT_READ_OWN,
        REPORT_UPLOAD_OWN,
        RISK_READ_OWN,
        RISK_REQUEST_OWN,
        APPOINTMENT_BOOK,
        NOTIFICATION_READ_OWN,
    ],
    Role.DOCTOR: [
        PATIENT_REGISTER,
        PATIENT_READ_ASSIGNED,
        RECORD_READ_ASSIGNED,
        REPORT_READ_ASSIGNED,
        RISK_READ_ASSIGNED,
        RISK_REQUEST,
        RISK_REVIEW,
        CLINICAL_NOTE_CREATE,
        ALERT_MANAGE,
        MISSING_DATA_REQUEST,
        AI_USE,
        APPOINTMENT_MANAGE,
        NOTIFICATION_READ_OWN,
    ],
    Role.LAB_TECHNICIAN: [
        LAB_WORKFLOW_ACCESS,
        LAB_PATIENT_IDENTITY_READ_MIN,
        LAB_REPORT_UPLOAD,
        LAB_RESULT_ENTER,
        LAB_RESULT_VALIDATE,
        LAB_TASK_PROCESS,
        LAB_MISSING_DATA_RESOLVE,
        NOTIFICATION_READ_OWN,
    ],
    Role.ADMIN: [
        USERS_MANAGE,
        ROLES_MANAGE,
        PERMISSIONS_MANAGE,
        SYSTEM_CONFIG_MANAGE,
        MODEL_METADATA_MANAGE,
        MODEL_GOVERNANCE_MANAGE,
        AUDIT_READ,
        PATIENT_IDENTITY_MANAGE,
        RECONCILIATION_MANAGE,
        STAFF_MANAGE,
        PATIENT_REGISTER,
        NOTIFICATION_READ_OWN,
    ],
}


def all_permission_codes() -> list[str]:
    return sorted(PERMISSION_CATALOG)


class PermissionResolver:
    """Resolves the effective permission set for a user.

    The result is memoized on the ``User`` instance for the life of that
    instance (i.e. one request). No process-global or cross-request state is
    used (spec section 7).
    """

    _CACHE_ATTR = "_caresense_permission_codes"

    @classmethod
    def permission_codes(cls, user) -> frozenset[str]:
        if user is None or not getattr(user, "is_authenticated", False):
            return frozenset()
        cached = getattr(user, cls._CACHE_ATTR, None)
        if cached is not None:
            return cached
        if getattr(user, "is_superuser", False):
            codes = frozenset(all_permission_codes())
        else:
            codes = frozenset(
                RolePermissionQuery.codes_for_user(user.pk)
            )
        setattr(user, cls._CACHE_ATTR, codes)
        return codes

    @classmethod
    def has(cls, user, code: str) -> bool:
        return code in cls.permission_codes(user)

    @classmethod
    def has_any(cls, user, *codes: str) -> bool:
        held = cls.permission_codes(user)
        return any(code in held for code in codes)

    @classmethod
    def require(cls, user, code: str) -> None:
        if not cls.has(user, code):
            raise AccessDenied(details={"required_permission": code})

    @classmethod
    def invalidate(cls, user) -> None:
        if hasattr(user, cls._CACHE_ATTR):
            delattr(user, cls._CACHE_ATTR)


class RolePermissionQuery:
    """Isolated so it can be swapped/mocked and so imports stay lazy."""

    @staticmethod
    def codes_for_user(user_pk) -> set[str]:
        from apps.accounts.models import Permission

        return set(
            Permission.objects.filter(
                roles__role_users__user_id=user_pk
            )
            .values_list("code", flat=True)
            .distinct()
        )


class HasPermission(BasePermission):
    """DRF permission class factory.

    Usage::

        permission_classes = [IsAuthenticated, HasPermission.of("risk.request")]
    """

    required_code: str = ""

    @classmethod
    def of(cls, code: str) -> type[HasPermission]:
        return type(f"HasPermission_{code}", (cls,), {"required_code": code})

    def has_permission(self, request, view) -> bool:
        return PermissionResolver.has(request.user, self.required_code)
