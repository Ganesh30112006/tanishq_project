"""Enforcing consent, and carrying out erasure honestly.

The interesting function here is :meth:`PrivacyService.execute_erasure`. It does
not delete a patient. It destroys the identifiers that make the record a
*person* and leaves the clinical observations behind as an unlinkable series,
then writes down exactly that, in words, on the request - because the one thing
worse than not deleting someone's data is telling them you did.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.errors import ValidationFailed
from apps.common.services import BaseService
from apps.privacy.models import (
    ConsentDocument,
    ConsentGrant,
    ConsentPurpose,
    ErasureRequest,
    ErasureState,
    RetentionPolicy,
)

#: Written into name fields so a de-identified row still reads as deliberate
#: rather than as corruption someone should try to "fix".
REDACTED = "[erased]"


class PrivacyService(BaseService):
    # -- consent ----------------------------------------------------------
    def current_document(self, purpose: str) -> ConsentDocument | None:
        return (
            ConsentDocument.objects.filter(
                purpose=purpose, effective_from__lte=timezone.now()
            )
            .order_by("-effective_from")
            .first()
        )

    @transaction.atomic
    def record_consent(
        self,
        *,
        patient,
        purpose: str,
        granted: bool,
        recorded_by=None,
        self_recorded: bool = True,
    ) -> ConsentGrant:
        """Record agreement, or its withdrawal, against the current wording."""
        if purpose not in ConsentPurpose.values:
            raise ValidationFailed(f"Unknown consent purpose '{purpose}'.")
        document = self.current_document(purpose)
        if document is None:
            raise ValidationFailed(
                f"No consent wording is published for '{purpose}', so agreement "
                f"to it cannot be recorded."
            )

        now = timezone.now()
        grant, _ = ConsentGrant.objects.get_or_create(
            patient=patient,
            purpose=purpose,
            defaults={"document": document, "recorded_by": recorded_by},
        )
        grant.document = document
        grant.recorded_by = recorded_by
        grant.self_recorded = self_recorded
        if granted:
            grant.granted_at = now
            grant.withdrawn_at = None
        else:
            grant.withdrawn_at = now
        grant.save()

        audit_service.record(
            audit.CONSENT_CHANGE,
            actor=recorded_by,
            resource=patient,
            metadata={
                "consent_purpose": purpose,
                "granted": granted,
                "document_version": document.version,
            },
        )
        return grant

    def has_consent(self, patient, purpose: str) -> bool:
        """Whether this processing is currently permitted for this patient.

        Absence of a grant is **not** consent. A purpose nobody has been asked
        about yet returns False, so a new purpose cannot start operating on
        people who were never shown it.
        """
        grant = ConsentGrant.objects.filter(patient=patient, purpose=purpose).first()
        return bool(grant and grant.is_active)

    def require_consent(self, patient, purpose: str) -> None:
        if self.has_consent(patient, purpose):
            return
        label = ConsentPurpose(purpose).label
        raise ValidationFailed(
            f"This needs your permission first: {label}. You can give or "
            f"withdraw it any time in your privacy settings."
        )

    def enforce_if_published(self, patient, purpose: str) -> None:
        """Require consent for this purpose, but only once wording exists for it.

        The alternative shapes are both wrong. Enforcing before any wording is
        published would block every deployment on day one for a purpose nobody
        has been able to agree to yet. Never enforcing would make consent
        decorative. So publishing the wording is the deliberate act that turns
        enforcement on, and ``manage.py check_privacy`` reports any purpose
        still unpublished so the gap is visible rather than silent.
        """
        if self.current_document(purpose) is None:
            return
        self.require_consent(patient, purpose)

    def unconfigured_purposes(self) -> list[str]:
        """Purposes with no published wording, and so no consent enforcement."""
        return [
            purpose
            for purpose in ConsentPurpose.values
            if self.current_document(purpose) is None
        ]

    def consent_summary(self, patient) -> list[dict]:
        """Every purpose and where this patient stands on it - including the
        ones never answered, which is what makes the list honest."""
        grants = {g.purpose: g for g in ConsentGrant.objects.filter(patient=patient)}
        out = []
        for purpose in ConsentPurpose.values:
            grant = grants.get(purpose)
            document = self.current_document(purpose)
            out.append(
                {
                    "purpose": purpose,
                    "label": ConsentPurpose(purpose).label,
                    "granted": bool(grant and grant.is_active),
                    "answered": grant is not None,
                    "granted_at": grant.granted_at if grant else None,
                    "withdrawn_at": grant.withdrawn_at if grant else None,
                    "document_version": document.version if document else None,
                    "is_essential": document.is_essential if document else False,
                }
            )
        return out

    # -- erasure ----------------------------------------------------------
    @transaction.atomic
    def request_erasure(self, *, patient, requested_by=None, reason: str = "") -> ErasureRequest:
        existing = ErasureRequest.objects.filter(
            patient=patient,
            state__in=[ErasureState.REQUESTED, ErasureState.UNDER_REVIEW],
        ).first()
        if existing is not None:
            return existing

        request = ErasureRequest.objects.create(
            patient=patient, requested_by=requested_by, reason=reason
        )
        audit_service.record(
            audit.ERASURE_REQUEST,
            actor=requested_by,
            resource=patient,
            metadata={"erasure_requested": str(request.public_id)},
        )
        return request

    def retention_floor(self, *, now: dt.datetime | None = None) -> dt.date:
        """The earliest date the clinical record may actually be destroyed."""
        now = now or timezone.now()
        policy = RetentionPolicy.objects.filter(
            category="CLINICAL_RECORD", is_active=True
        ).first()
        days = policy.retain_days if policy else 0
        return (now + dt.timedelta(days=days)).date()

    @transaction.atomic
    def execute_erasure(self, request: ErasureRequest, *, decided_by=None) -> ErasureRequest:
        """De-identify the patient. Clinical observations survive, unlinkable.

        What is destroyed: name, date of birth, phone, the medical record
        number, and the login. What remains: the measurements, results and
        assessments, now attached to a record that identifies nobody.

        Why not a delete: the clinical rows are append-only and are separately
        subject to a retention obligation. Removing the identifiers achieves
        what the right is actually for - the data can no longer be connected to
        the person - without destroying evidence a clinician may be required to
        produce.
        """
        if request.state == ErasureState.COMPLETED:
            return request
        if request.state in (ErasureState.REFUSED, ErasureState.WITHDRAWN):
            raise ValidationFailed("This erasure request is already closed.")

        patient = request.patient
        now = timezone.now()

        # A one-way token: enough to keep rows distinct, useless for identifying
        # anyone. The original MRN is not recoverable from it because the salt
        # is generated here and never stored.
        shred = hashlib.sha256(
            f"{patient.public_id}:{secrets.token_hex(32)}".encode()
        ).hexdigest()[:24]

        had_login = patient.user is not None
        login = patient.user

        patient.given_name = REDACTED
        patient.family_name = REDACTED
        patient.date_of_birth = None
        patient.phone = ""
        patient.mrn = f"ERASED-{shred}"
        patient.user = None
        patient.is_active = False
        patient.save(
            update_fields=[
                "given_name", "family_name", "date_of_birth", "phone",
                "mrn", "user", "is_active", "updated_at",
            ]
        )

        # The login is a separate identifier and goes too, along with every
        # credential it holds - otherwise a session outlives the erasure.
        if had_login and login is not None:
            from apps.accounts.services import AccountService

            AccountService().revoke_all_for_user(login)
            login.is_active = False
            login.email = f"erased-{shred}@invalid"
            login.set_unusable_password()
            login.save(update_fields=["is_active", "email", "password"])

        retained_until = self.retention_floor(now=now)
        request.state = ErasureState.COMPLETED
        request.decided_by = decided_by
        request.decided_at = now
        request.executed_at = now
        request.retained_until = retained_until
        request.outcome_summary = (
            "Your name, date of birth, phone number, record number and login "
            "have been destroyed and cannot be recovered. Your medical "
            "observations - measurements, laboratory results and assessments - "
            "have been kept, but they are no longer connected to you or to any "
            "other person, and nobody can tell they were yours. They are kept "
            f"because a treatment record must be retained until {retained_until} "
            "before it may be destroyed. The audit trail of who looked at the "
            "record is kept for the same reason, and it too no longer names you."
        )
        request.save()

        audit_service.record(
            audit.ERASURE_EXECUTE,
            actor=decided_by,
            resource=patient,
            metadata={
                "erasure_executed": str(request.public_id),
                "identifiers_destroyed": True,
                "clinical_rows_retained": True,
                "retained_until": str(retained_until),
            },
        )
        return request

    @transaction.atomic
    def refuse_erasure(
        self, request: ErasureRequest, *, decided_by=None, note: str
    ) -> ErasureRequest:
        if not note.strip():
            raise ValidationFailed("A refusal must say why.")
        request.state = ErasureState.REFUSED
        request.decided_by = decided_by
        request.decided_at = timezone.now()
        request.decision_note = note
        request.outcome_summary = (
            "Your request could not be carried out at this time. The reason is "
            "recorded above. You may ask again, and you may withdraw your "
            "agreement to any optional processing straight away."
        )
        request.save()
        return request


privacy_service = PrivacyService()
