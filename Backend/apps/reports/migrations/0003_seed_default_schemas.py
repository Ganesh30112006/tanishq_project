"""Seed the default expected-report schemas (spec section 14). Re-runnable."""
from __future__ import annotations

from django.db import migrations


def seed(apps, schema_editor):
    from apps.reports.default_schemas import DEFAULT_SCHEMAS

    ReportSchema = apps.get_model("reports", "ReportSchema")
    for entry in DEFAULT_SCHEMAS:
        ReportSchema.objects.update_or_create(
            report_class=entry["report_class"],
            version=entry["version"],
            defaults={"status": "ACTIVE", "definition": entry["definition"]},
        )


def unseed(apps, schema_editor):
    ReportSchema = apps.get_model("reports", "ReportSchema")
    ReportSchema.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0002_report_class_hint_report_extracted_text")]
    operations = [migrations.RunPython(seed, unseed)]
