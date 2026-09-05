"""Seed default escalation policies (spec section 27). Re-runnable.

Steps are ordered by ``after_hours`` and each is applied at most once as the
task ages past that boundary.
"""
from __future__ import annotations

from django.db import migrations

POLICIES = [
    {
        "source_workflow": "lab_result",
        "sla_hours": 24,
        "steps": [
            {"after_hours": 24, "raise_priority_to": "high"},
            {"after_hours": 48, "raise_priority_to": "urgent", "reassign_role": "ADMIN"},
        ],
    },
    {
        "source_workflow": "risk_assessment",
        "sla_hours": 48,
        "steps": [
            {"after_hours": 48, "raise_priority_to": "high"},
            {"after_hours": 96, "raise_priority_to": "urgent", "reassign_role": "ADMIN"},
        ],
    },
    {
        "source_workflow": "clinical_assessment",
        "sla_hours": 48,
        "steps": [
            {"after_hours": 48, "raise_priority_to": "high"},
            {"after_hours": 120, "raise_priority_to": "urgent", "reassign_role": "ADMIN"},
        ],
    },
    {
        "source_workflow": "report_review",
        "sla_hours": 72,
        "steps": [{"after_hours": 72, "raise_priority_to": "high"}],
    },
    {
        "source_workflow": "system",
        "sla_hours": 24,
        "steps": [{"after_hours": 24, "raise_priority_to": "high"}],
    },
]


def seed(apps, schema_editor):
    EscalationPolicy = apps.get_model("notifications", "EscalationPolicy")
    for p in POLICIES:
        EscalationPolicy.objects.update_or_create(
            source_workflow=p["source_workflow"],
            defaults={"sla_hours": p["sla_hours"], "steps": p["steps"], "is_active": True},
        )


def unseed(apps, schema_editor):
    EscalationPolicy = apps.get_model("notifications", "EscalationPolicy")
    EscalationPolicy.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_escalationpolicy_missingdatatask_escalation_level_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
