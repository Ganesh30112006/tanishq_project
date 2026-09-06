"""Consent, retention and erasure.

India's Digital Personal Data Protection Act gives a person the right to know
what was collected, to withdraw agreement to its processing, and to ask for
erasure. A clinical system cannot simply honour the last of those with a
``DELETE``, and pretending otherwise is worse than saying so plainly:

* **Clinical history is append-only** here by design, because a record that can
  be silently rewritten is not evidence of anything.
* **Retention is separately obligatory.** A treatment record has to be kept for
  a minimum period regardless of what anyone wants; discarding it can harm the
  patient it belonged to and expose the clinician who relied on it.

So erasure is implemented as **de-identification**: the identifiers that make a
row a *person* are destroyed, and the clinical observations survive as an
unlinkable series. What was actually done is recorded on the request, so nobody
is told their data vanished when it did not.
"""
from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import AppendOnlyModel, UUIDTimeStampedModel


class ConsentPurpose(models.TextChoices):
    """Consent is per purpose. A single "I agree" covering everything is not
    informed agreement, and withdrawing from one use must not end the others."""

    CARE = "CARE", "Providing care and holding my health record"
    RISK_ANALYSIS = "RISK_ANALYSIS", "Automated risk estimates from my record"
    AI_ASSISTANCE = "AI_ASSISTANCE", "AI summaries of my record"
    RESEARCH = "RESEARCH", "De-identified data used for research"
    COMMUNICATIONS = "COMMUNICATIONS", "Reminders and messages about my care"


class ConsentDocument(AppendOnlyModel):
    """The exact wording a person agreed to, frozen.

    Append-only on purpose: proving consent means being able to show the text
    as it stood on the day, not the text as edited since. A change is a new
    version, and old grants keep pointing at the version they were given for.
    """

    purpose = models.CharField(max_length=32, choices=ConsentPurpose.choices)
    version = models.CharField(max_length=20)
    body = models.TextField(help_text="The wording shown to the person, verbatim.")
    effective_from = models.DateTimeField(default=timezone.now)
    #: Withdrawing this purpose stops the processing it covers. Care itself
    #: cannot be switched off while a record is being maintained, so that one
    #: is marked essential and withdrawal closes the record instead.
    is_essential = models.BooleanField(default=False)

    class Meta:
        db_table = "privacy_consent_document"
        constraints = [
            models.UniqueConstraint(
                fields=["purpose", "version"], name="uq_consent_purpose_version"
            )
        ]
        ordering = ["purpose", "-effective_from"]

    def __str__(self) -> str:
        return f"{self.purpose} v{self.version}"


class ConsentGrant(UUIDTimeStampedModel):
    """One person's answer to one consent document.

    Not append-only, because withdrawal has to be recordable on the same row -
    but the row is never deleted and ``granted_at``/``withdrawn_at`` keep the
    whole history readable.
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="consent_grants"
    )
    document = models.ForeignKey(
        ConsentDocument, on_delete=models.PROTECT, related_name="grants"
    )
    purpose = models.CharField(max_length=32, choices=ConsentPurpose.choices)
    granted_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    #: Who recorded it. A grant captured by staff on someone's behalf is a
    #: different kind of evidence from one the person entered themselves.
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    self_recorded = models.BooleanField(default=True)

    class Meta:
        db_table = "privacy_consent_grant"
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "purpose"], name="uq_consent_patient_purpose"
            )
        ]
        indexes = [models.Index(fields=["patient", "purpose"])]

    def __str__(self) -> str:
        state = "granted" if self.is_active else "withdrawn"
        return f"{self.patient_id}:{self.purpose} ({state})"

    @property
    def is_active(self) -> bool:
        return self.granted_at is not None and self.withdrawn_at is None


class ErasureState(models.TextChoices):
    REQUESTED = "REQUESTED", "Requested"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    #: Identifiers destroyed, clinical series retained unlinkably.
    COMPLETED = "COMPLETED", "Completed"
    #: Refused because a retention obligation currently overrides the request.
    REFUSED = "REFUSED", "Refused"
    WITHDRAWN = "WITHDRAWN", "Withdrawn by the requester"


class ErasureRequest(UUIDTimeStampedModel):
    """A person asking to be forgotten, and exactly what was done about it."""

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="erasure_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    state = models.CharField(
        max_length=16, choices=ErasureState.choices, default=ErasureState.REQUESTED
    )
    reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    #: A plain-language account of what was destroyed and what was kept, so the
    #: person is never told "deleted" when the answer is "de-identified".
    outcome_summary = models.TextField(blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    #: Retained rows are eligible for real destruction only after this date.
    retained_until = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "privacy_erasure_request"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["state", "created_at"])]

    def __str__(self) -> str:
        return f"erasure:{self.patient_id}:{self.state}"


class RetentionCategory(models.TextChoices):
    CLINICAL_RECORD = "CLINICAL_RECORD", "Clinical record"
    UPLOADED_REPORT = "UPLOADED_REPORT", "Uploaded report file"
    AUDIT_LOG = "AUDIT_LOG", "Audit log"
    AI_INTERACTION = "AI_INTERACTION", "AI interaction"
    ACCESS_TOKEN = "ACCESS_TOKEN", "Expired credential"
    NOTIFICATION = "NOTIFICATION", "Notification"


class RetentionPolicy(UUIDTimeStampedModel):
    """How long one category is kept, and the reason it is kept that long.

    ``basis`` is not decoration. "We kept it for eight years" is only defensible
    if somebody can say which obligation required eight years, and a policy row
    without a stated basis is a guess that has hardened into a default.
    """

    category = models.CharField(
        max_length=32, choices=RetentionCategory.choices, unique=True
    )
    retain_days = models.PositiveIntegerField()
    basis = models.TextField(help_text="The obligation or reason for this period.")
    #: What happens at expiry. De-identification is the default for anything
    #: clinical; only genuinely disposable rows are deleted outright.
    hard_delete = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "privacy_retention_policy"
        ordering = ["category"]

    def __str__(self) -> str:
        return f"{self.category}: {self.retain_days}d"

    def cutoff(self, *, now: dt.datetime | None = None) -> dt.datetime:
        return (now or timezone.now()) - dt.timedelta(days=self.retain_days)
