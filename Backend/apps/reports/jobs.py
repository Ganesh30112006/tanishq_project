"""Background job handlers for the reports app (spec section 47).

The ``reports.process`` job runs the deterministic pipeline. The payload
carries only the report's ``public_id``; the handler re-loads the row, so it
is safe to retry and idempotent (a finalized report is not re-processed).

``reports.analyse`` runs the patient-facing AI analysis. It is its own job so
that the AI being slow or down can never hold up, fail or retry the pipeline.
"""
from __future__ import annotations

from apps.jobs.runner import register
from apps.jobs.services import JobService
from apps.reports import analysis
from apps.reports.models import Report
from apps.reports.pipeline import ReportPipeline


@register("reports.process")
def process_report(payload: dict) -> dict:
    report = Report.objects.get(public_id=payload["report_id"])
    result = ReportPipeline().run(report)
    if analysis.enabled():
        report.refresh_from_db()
        enqueue_analysis(report)
    return {
        "report_id": payload["report_id"],
        "processing_state": result.value.report.processing_state if result.value else None,
        "ok": result.ok,
        "outcome": result.code,
    }


@register("reports.analyse")
def analyse_report(payload: dict) -> dict:
    report = Report.objects.select_related("patient").get(public_id=payload["report_id"])
    result = analysis.analyse(report)
    return {"report_id": payload["report_id"], "status": result.status, "reason": result.reason_code}


def enqueue_analysis(report: Report) -> None:
    JobService().enqueue(
        "reports.analyse",
        payload={"report_id": str(report.public_id)},
        idempotency_key=f"reports.analyse:{report.public_id}:{report.version}:{analysis.POLICY_VERSION}",
    )
