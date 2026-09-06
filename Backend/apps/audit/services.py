"""AuditService - the single way application code writes audit rows.

Critical workflows call this explicitly (spec section 56); auditing is not
hidden inside model ``save()`` signals.
"""
from __future__ import annotations

from typing import Any

from django.db import models

from apps.audit import context
from apps.audit.models import AuditLog
from apps.common.enums import AuditResult

# Action name constants (spec section 41).
LOGIN = "auth.login"
LOGIN_FAILED = "auth.login.failed"
LOGOUT = "auth.logout"
PATIENT_ACCESS = "patient.access"
RECORD_MODIFY = "record.modify"
REPORT_UPLOAD = "report.upload"
REPORT_ACCESS = "report.access"
REPORT_PROCESSED = "report.processed"
LAB_RESULT_CHANGE = "lab_result.change"
RISK_ASSESSMENT = "risk.assessment"
MODEL_GOVERNANCE = "model.governance"
CLINICAL_REVIEW = "clinical.review"
AI_INTERACTION = "ai.interaction"
ALERT_CREATE = "alert.create"
PERMISSION_CHANGE = "permission.change"
ROLE_CHANGE = "role.change"
ADMIN_CHANGE = "admin.change"
USER_CREATE = "user.create"
PATIENT_REGISTER = "patient.register"
PATIENT_ACCOUNT_LINK = "patient.account.link"
STAFF_CHANGE = "staff.change"
ASSIGNMENT_CHANGE = "assignment.change"
APPOINTMENT_CHANGE = "appointment.change"
RECONCILIATION_ACTION = "reconciliation.action"
MISSING_DATA_ACTION = "missing_data.action"
ACCESS_DENIED = "access.denied"
# Privacy actions are audited like clinical ones: a consent change or an
# erasure is a decision about a person that somebody must be able to review.
CONSENT_CHANGE = "privacy.consent.change"
ERASURE_REQUEST = "privacy.erasure.request"
ERASURE_EXECUTE = "privacy.erasure.execute"
RETENTION_SWEEP = "privacy.retention.sweep"


class AuditService:
    def record(
        self,
        action: str,
        *,
        actor: Any | None = None,
        resource: models.Model | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        result: str = AuditResult.SUCCESS,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        ctx = context.current()

        if resource is not None:
            resource_type = resource_type or resource.__class__.__name__
            resource_id = resource_id or str(
                getattr(resource, "public_id", getattr(resource, "pk", ""))
            )

        actor_label = ""
        actor_roles: list[str] = []
        if actor is not None and getattr(actor, "is_authenticated", False):
            actor_label = actor.get_username()
            actor_roles = sorted(getattr(actor, "role_codes", set()))
        elif ctx.actor_label:
            actor_label = ctx.actor_label

        return AuditLog.objects.create(
            actor=actor if getattr(actor, "pk", None) else None,
            actor_label=actor_label,
            actor_roles=actor_roles,
            action=action,
            resource_type=resource_type or "",
            resource_id=(resource_id or "")[:64],
            result=result,
            reason=reason[:255],
            request_id=ctx.request_id or "",
            client_ip=ctx.client_ip,
            user_agent=ctx.user_agent or "",
            metadata=_scrub(metadata or {}),
        )

    def denied(self, action: str, *, actor: Any | None = None, reason: str = "", **kw: Any) -> AuditLog:
        return self.record(action, actor=actor, result=AuditResult.DENIED, reason=reason, **kw)


_SENSITIVE_HINTS = ("value", "result_value", "glucose", "hba1c", "bp", "spo2", "note", "text")


def _scrub(metadata: dict[str, Any]) -> dict[str, Any]:
    """Best-effort guard so callers do not accidentally persist clinical values
    in the audit trail (spec section 41)."""
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if any(hint in key.lower() for hint in _SENSITIVE_HINTS):
            cleaned[key] = "[redacted]"
        else:
            cleaned[key] = value
    return cleaned


audit_service = AuditService()
