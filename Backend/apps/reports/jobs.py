"""Background job handlers for the reports app (spec section 47).

The ``reports.process`` job runs the deterministic pipeline. The payload
carries only the report's ``public_id``; the handler re-loads the row, so it
is safe to retry and idempotent (a finalized report is not re-processed).
"""
from __future__ import annotations

from apps.jobs.runner import register
from apps.reports.models import Report
from apps.reports.pipeline import ReportPipeline


@register("reports.process")
def process_report(payload: dict) -> dict:
    report = Report.objects.get(public_id=payload["report_id"])
    result = ReportPipeline().run(report)
    return {
        "report_id": payload["report_id"],
        "processing_state": result.value.report.processing_state if result.value else None,
        "ok": result.ok,
        "outcome": result.code,
    }
