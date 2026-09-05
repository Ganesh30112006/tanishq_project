"""Seed a small set of approved general-knowledge documents (spec section 36).

These are generic reference notes, never patient data. Re-runnable.
"""
from __future__ import annotations

from django.db import migrations

DOCS = [
    {
        "title": "Understanding an HbA1c result",
        "category": "lab_explainer",
        "body": (
            "HbA1c (glycated haemoglobin) reflects average blood glucose over roughly "
            "the previous 2-3 months. It is commonly reported in mmol/mol (IFCC) or as "
            "a percentage (NGSP). This note explains what the test measures; it is not "
            "specific to any patient and is not medical advice."
        ),
        "source": "internal reference",
    },
    {
        "title": "Reading a lipid profile",
        "category": "lab_explainer",
        "body": (
            "A lipid profile typically reports total cholesterol, HDL cholesterol, LDL "
            "cholesterol and triglycerides. Values may be given in mg/dL or mmol/L. "
            "Interpretation depends on individual clinical context and should be done "
            "by a clinician."
        ),
        "source": "internal reference",
    },
    {
        "title": "What a fasting glucose measures",
        "category": "lab_explainer",
        "body": (
            "Fasting plasma glucose is measured after at least 8 hours without caloric "
            "intake. Units are mg/dL or mmol/L. This is background information only."
        ),
        "source": "internal reference",
    },
]


def seed(apps, schema_editor):
    AiKnowledgeDocument = apps.get_model("ai", "AiKnowledgeDocument")
    for doc in DOCS:
        AiKnowledgeDocument.objects.update_or_create(
            title=doc["title"],
            defaults={**doc, "version": 1, "is_approved": True},
        )


def unseed(apps, schema_editor):
    AiKnowledgeDocument = apps.get_model("ai", "AiKnowledgeDocument")
    AiKnowledgeDocument.objects.filter(title__in=[d["title"] for d in DOCS]).delete()


class Migration(migrations.Migration):
    dependencies = [("ai", "0002_aiknowledgedocument")]
    operations = [migrations.RunPython(seed, unseed)]
