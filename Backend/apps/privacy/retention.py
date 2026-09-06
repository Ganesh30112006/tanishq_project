"""Applying retention periods.

Keeping data forever is a decision, not a default, and it is usually the wrong
one: every extra year of retention is another year the data can be breached,
subpoenaed or misused, for no clinical benefit once the obligation has lapsed.

The sweep is **report-first**. It can tell you what is expiring without
touching anything, because a retention job that silently destroys clinical data
the first time somebody runs it is far more dangerous than one that has to be
asked twice.
"""
from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.privacy.models import RetentionCategory, RetentionPolicy

#: Seeded on first run. These are starting points a compliance owner must
#: review against the obligations that actually bind this deployment - they are
#: not legal advice, and the ``basis`` text says where each number came from.
DEFAULT_POLICIES: list[dict] = [
    {
        "category": RetentionCategory.CLINICAL_RECORD,
        "retain_days": 3 * 365,
        "basis": (
            "Indian medical-records practice keeps an outpatient record for at "
            "least 3 years from the last entry. Confirm against the obligations "
            "for this deployment - inpatient, paediatric and medico-legal "
            "records are commonly held far longer."
        ),
        "hard_delete": False,
    },
    {
        "category": RetentionCategory.UPLOADED_REPORT,
        "retain_days": 3 * 365,
        "basis": (
            "The source document behind a clinical value is part of the record "
            "it supports, so it is kept as long as that record."
        ),
        "hard_delete": False,
    },
    {
        "category": RetentionCategory.AUDIT_LOG,
        "retain_days": 8 * 365,
        "basis": (
            "The audit trail outlives the record it describes, otherwise there "
            "is no way to answer who looked at a record during the period it "
            "existed. Deliberately the longest period here."
        ),
        "hard_delete": False,
    },
    {
        "category": RetentionCategory.AI_INTERACTION,
        "retain_days": 365,
        "basis": (
            "A generated summary is derived, never a source of clinical truth, "
            "so it is kept only long enough to review the output that informed "
            "a decision."
        ),
        "hard_delete": False,
    },
    {
        "category": RetentionCategory.ACCESS_TOKEN,
        "retain_days": 30,
        "basis": (
            "An expired or revoked credential has no further use. Kept briefly "
            "so a session can be investigated after the fact, then removed - "
            "this is the one category safe to delete outright."
        ),
        "hard_delete": True,
    },
    {
        "category": RetentionCategory.NOTIFICATION,
        "retain_days": 180,
        "basis": "Operational messages, of no evidentiary value once acted on.",
        "hard_delete": True,
    },
]


def seed_default_policies() -> int:
    created = 0
    for spec in DEFAULT_POLICIES:
        _, made = RetentionPolicy.objects.get_or_create(
            category=spec["category"],
            defaults={
                "retain_days": spec["retain_days"],
                "basis": spec["basis"],
                "hard_delete": spec["hard_delete"],
            },
        )
        created += int(made)
    return created


def _expired_counts(now: dt.datetime) -> list[dict]:
    """What each active policy would act on, without acting on it."""
    from apps.accounts.models import AccessToken, RefreshToken
    from apps.ai.models import AiInteraction
    from apps.audit.models import AuditLog
    from apps.notifications.models import Notification
    from apps.reports.models import Report

    rows = []
    for policy in RetentionPolicy.objects.filter(is_active=True):
        cutoff = policy.cutoff(now=now)
        if policy.category == RetentionCategory.ACCESS_TOKEN:
            count = (
                AccessToken.objects.filter(expires_at__lt=cutoff).count()
                + RefreshToken.objects.filter(expires_at__lt=cutoff).count()
            )
        elif policy.category == RetentionCategory.NOTIFICATION:
            count = Notification.objects.filter(created_at__lt=cutoff).count()
        elif policy.category == RetentionCategory.AI_INTERACTION:
            count = AiInteraction.objects.filter(created_at__lt=cutoff).count()
        elif policy.category == RetentionCategory.AUDIT_LOG:
            count = AuditLog.objects.filter(created_at__lt=cutoff).count()
        elif policy.category == RetentionCategory.UPLOADED_REPORT:
            count = Report.objects.filter(created_at__lt=cutoff).count()
        else:
            count = 0
        rows.append(
            {
                "category": policy.category,
                "retain_days": policy.retain_days,
                "cutoff": cutoff,
                "expired": count,
                "action": "delete" if policy.hard_delete else "review / de-identify",
                "basis": policy.basis,
            }
        )
    return rows


def sweep(*, apply: bool = False, now: dt.datetime | None = None) -> dict:
    """Report what has passed its retention period, and optionally act.

    Only ``hard_delete`` categories are ever acted on automatically, and those
    are the ones with no evidentiary value: expired credentials and delivered
    notifications. Anything clinical is reported for a person to decide, because
    an automated job is the wrong thing to put in charge of destroying a
    medical record.
    """
    now = now or timezone.now()
    rows = _expired_counts(now)
    deleted: dict[str, int] = {}

    if apply:
        from apps.accounts.models import AccessToken, RefreshToken
        from apps.notifications.models import Notification

        for policy in RetentionPolicy.objects.filter(is_active=True, hard_delete=True):
            cutoff = policy.cutoff(now=now)
            if policy.category == RetentionCategory.ACCESS_TOKEN:
                n1, _ = AccessToken.objects.filter(expires_at__lt=cutoff).delete()
                n2, _ = RefreshToken.objects.filter(expires_at__lt=cutoff).delete()
                deleted[policy.category] = n1 + n2
            elif policy.category == RetentionCategory.NOTIFICATION:
                n, _ = Notification.objects.filter(created_at__lt=cutoff).delete()
                deleted[policy.category] = n

    return {
        "generated_at": now,
        "applied": apply,
        "policies": rows,
        "deleted": deleted,
        "needs_human_decision": [
            r for r in rows if r["expired"] and r["action"] != "delete"
        ],
    }
