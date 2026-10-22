"""The patient-facing AI analysis: what it shows, and what it holds back.

There is no doctor in the loop, so holding back is the safety mechanism. These
tests hold the analysis to one direction:

* a value the AI is not sure of, or that the existing pipeline read
  differently, is never used - and neither is anything built on it;
* holding back is always said, with a reason, never shown as a clean result;
* the AI being down changes nothing about the report;
* the analysis is AI output - it never writes a clinical value;
* a patient sees the analysis of their own reports and nobody else's.
"""
from __future__ import annotations

import pytest

from apps.common.enums import ReportClass, Role
from apps.reports import analysis
from apps.reports.models import ReportAnalysis, ReportTest
from apps.reports.pipeline import ReportPipeline

pytestmark = pytest.mark.django_db

CLEAN_GLUCOSE = """
CHEMISTRY
Collected: 2024-05-01 09:00
Reported: 2024-05-01 15:00
Glucose: 5.4 mmol/L
"""


# --- helpers ---------------------------------------------------------
class _FakeResult:
    def __init__(self, *, disposition="EXTRACTED", values=None, findings=None):
        self.disposition = disposition
        self.values = values or []
        self.findings = findings
        self.source_sha256 = "abc"
        self.text_source = "EMBEDDED_TEXT_LAYER"


class _FakeClient:
    def __init__(self, result=None, *, error=None):
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def process_document(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def _value(analyte, value, unit, *, persists=True, reason="", flag="", status="OBSERVED"):
    return {
        "analyte": analyte,
        "printed_label": analyte.title(),
        "value": value,
        "unit": unit,
        "status": status,
        "reason": reason,
        "printed_flag": flag,
        "persists_clinical_value": persists,
        "reference_range": {"text": "3.9 - 5.5"},
        "reference_status": "WITHIN",
        "provenance": {"page": 1, "source_text": f"{analyte} {value} {unit}"},
    }


def _finding(code, level, *, measured=(), built_on=(), confidence="SUPPORTED"):
    refs = [{"key": k, "kind": "measurement", "value": 1.0} for k in measured]
    refs += [{"key": k, "kind": "finding"} for k in built_on]
    return {
        "code": code, "label": code, "level": level, "category": "test",
        "confidence": confidence, "validation_status": "NOT_VALIDATED",
        "evidence_used": refs, "evidence_missing": [], "caveats": [],
        "plain_name": f"{code} name", "plain_explanation": "approved text",
        "next_steps": ["Show this to a doctor."],
    }


def _findings(*items):
    return {
        "findings": list(items), "unusable_evidence": [], "detectors_run": 40,
        "range_table_version": "rt-1", "knowledge_version": "kn-1",
    }


def _upload(patient, uploader, text=CLEAN_GLUCOSE):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.reports.services import ReportService

    handle = SimpleUploadedFile("r.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    return ReportService().register_upload(
        patient=patient, uploaded_file=handle, uploaded_by=uploader,
        class_hint=ReportClass.GLUCOSE, extracted_text=text,
    )


@pytest.fixture
def report(make_patient, make_user):
    return _upload(make_patient(), make_user())


# --- availability ----------------------------------------------------
def test_service_down_is_unavailable_and_changes_nothing(report):
    state_before = report.processing_state
    tests_before = ReportTest.objects.count()

    result = analysis.analyse(report, client=_FakeClient(error=RuntimeError("down")))

    assert result.status == ReportAnalysis.Status.UNAVAILABLE
    assert result.reason_code == "service_unavailable"
    assert result.reason  # said, not silent
    report.refresh_from_db()
    assert report.processing_state == state_before
    assert ReportTest.objects.count() == tests_before


def test_unreadable_document_is_held_back_with_a_reason(report):
    result = analysis.analyse(report, client=_FakeClient(_FakeResult(disposition="UNREADABLE")))
    assert result.status == ReportAnalysis.Status.HELD_BACK
    assert result.reason_code == "could_not_read"
    assert result.values == [] and result.findings == []


# --- what is shown ---------------------------------------------------
def test_clean_read_shows_values_and_findings_with_approved_text(report):
    client = _FakeClient(_FakeResult(
        values=[_value("glucose", 5.4, "mmol/L")],
        findings=_findings(_finding("HYPERGLYCEMIA_PATTERN", 2, measured=["glucose"])),
    ))
    result = analysis.analyse(report, client=client)

    assert result.status == ReportAnalysis.Status.READY
    assert [v["state"] for v in result.values] == [analysis.USED]
    assert result.values[0]["source_text"] == "glucose 5.4 mmol/L"
    shown = result.findings[0]
    assert not shown["withheld"]
    assert shown["plain_explanation"] == "approved text"
    assert result.policy_version == analysis.POLICY_VERSION
    assert result.knowledge_version == "kn-1"


def test_patient_context_is_attributes_not_identifiers(report, make_patient):
    client = _FakeClient(_FakeResult(values=[_value("glucose", 5.4, "mmol/L")]))
    analysis.analyse(report, client=client)
    sent = client.calls[0]
    assert sent["document_id"] == str(report.public_id)
    assert "patient_id" not in sent and "mrn" not in sent


def test_value_the_ai_is_not_sure_of_is_not_used(report):
    client = _FakeClient(_FakeResult(
        values=[_value("glucose", 5.4, "mmol/L", persists=False, reason="LOW_OCR_CONFIDENCE")],
    ))
    result = analysis.analyse(report, client=client)

    assert result.values[0]["state"] == analysis.NOT_SURE
    assert result.values[0]["note"]
    # Nothing it stood behind, so nothing is presented as an analysis.
    assert result.status == ReportAnalysis.Status.HELD_BACK
    assert result.reason_code == "nothing_certain"


# --- holding back on disagreement -------------------------------------
def test_value_the_pipeline_read_differently_is_held_back_with_what_stood_on_it(report):
    ReportPipeline().run(report)  # the existing reader: glucose 5.4 mmol/L
    assert report.tests.filter(name="glucose").exists()

    client = _FakeClient(_FakeResult(
        values=[_value("glucose", 9.9, "mmol/L"), _value("hba1c", 6.1, "%")],
        findings=_findings(
            _finding("HYPERGLYCEMIA_PATTERN", 2, measured=["glucose"]),
            _finding("POSSIBLE_X", 3, built_on=["HYPERGLYCEMIA_PATTERN"]),
            _finding("ELEVATED_HBA1C_PATTERN", 2, measured=["hba1c"]),
        ),
    ))
    result = analysis.analyse(report, client=client)

    states = {v["analyte"]: v["state"] for v in result.values}
    assert states == {"glucose": analysis.READERS_DISAGREE, "hba1c": analysis.USED}
    withheld = {f["code"]: f["withheld"] for f in result.findings}
    assert withheld == {
        "HYPERGLYCEMIA_PATTERN": True,
        "POSSIBLE_X": True,  # built on a withheld pattern
        "ELEVATED_HBA1C_PATTERN": False,
    }
    assert all(f["withheld_reason"] for f in result.findings if f["withheld"])
    assert result.reason_code == "readers_disagree"
    assert result.status == ReportAnalysis.Status.READY


def test_withholding_follows_the_chain_whatever_order_findings_arrive_in():
    rows = analysis.withhold(
        [
            _finding("C", 3, built_on=["B"]),
            _finding("B", 2, measured=["sodium"]),
        ],
        {"sodium"},
    )
    assert {r["code"]: r["withheld"] for r in rows} == {"B": True, "C": True}


# --- urgency ---------------------------------------------------------
def test_a_critical_flag_is_urgent_even_on_a_held_back_value(report):
    ReportPipeline().run(report)
    client = _FakeClient(_FakeResult(
        values=[_value("glucose", 25.0, "mmol/L", flag="CRITICAL_HIGH")],
    ))
    result = analysis.analyse(report, client=client)
    assert result.values[0]["state"] == analysis.READERS_DISAGREE
    assert result.urgent is True


# --- never a clinical record ------------------------------------------
def test_analysis_never_writes_a_clinical_value(report):
    tests_before = ReportTest.objects.count()
    analysis.analyse(report, client=_FakeClient(_FakeResult(
        values=[_value("hba1c", 6.1, "%")],
        findings=_findings(_finding("ELEVATED_HBA1C_PATTERN", 2, measured=["hba1c"])),
    )))
    assert ReportTest.objects.count() == tests_before


def test_re_analysis_replaces_rather_than_accumulates(report):
    analysis.analyse(report, client=_FakeClient(error=RuntimeError("down")))
    analysis.analyse(report, client=_FakeClient(_FakeResult(values=[_value("hba1c", 6.1, "%")])))
    assert ReportAnalysis.objects.filter(report=report).count() == 1
    assert ReportAnalysis.objects.get(report=report).status == ReportAnalysis.Status.READY


# --- API -------------------------------------------------------------
def _patient_with_report(make_user, make_patient):
    user = make_user(Role.PATIENT)
    patient = make_patient(user=user)
    return user, _upload(patient, user)


def test_patient_reads_their_own_analysis(make_user, make_patient, auth_client):
    user, rep = _patient_with_report(make_user, make_patient)
    client = auth_client(user)

    pending = client.get(f"/api/v1/reports/{rep.public_id}/analysis/")
    assert pending.status_code == 200
    assert pending.json()["status"] == "PENDING"

    analysis.analyse(rep, client=_FakeClient(_FakeResult(values=[_value("hba1c", 6.1, "%")])))
    done = client.get(f"/api/v1/reports/{rep.public_id}/analysis/")
    assert done.status_code == 200
    assert done.json()["status"] == "READY"
    assert done.json()["values"][0]["analyte"] == "hba1c"


def test_another_patient_cannot_read_it(make_user, make_patient, auth_client):
    _, rep = _patient_with_report(make_user, make_patient)
    analysis.analyse(rep, client=_FakeClient(_FakeResult(values=[_value("hba1c", 6.1, "%")])))
    stranger, _ = _patient_with_report(make_user, make_patient)

    resp = auth_client(stranger).get(f"/api/v1/reports/{rep.public_id}/analysis/")
    assert resp.status_code == 404


def test_retry_only_reruns_a_read_that_never_happened(make_user, make_patient, auth_client):
    from apps.jobs.models import Job

    user, rep = _patient_with_report(make_user, make_patient)
    client = auth_client(user)
    analysis.analyse(rep, client=_FakeClient(_FakeResult(values=[_value("hba1c", 6.1, "%")])))

    resp = client.post(f"/api/v1/reports/{rep.public_id}/analyse/")
    assert resp.status_code == 200  # already analysed: returned, not re-queued
    assert not Job.objects.filter(job_type="reports.analyse").exists()

    analysis.analyse(rep, client=_FakeClient(error=RuntimeError("down")))
    resp = client.post(f"/api/v1/reports/{rep.public_id}/analyse/")
    assert resp.status_code == 202
    assert Job.objects.filter(job_type="reports.analyse").count() == 1
