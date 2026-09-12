"""The document service as a second reader, and the one direction it may move.

The existing pipeline works. Clinicians act on what it produces today, and the
benchmark corpora that would justify replacing it do not exist - so "the new
parser is better" is a belief, not a finding. The integration is therefore
built so that the belief does not have to be true for the change to be safe:

    a report the existing pipeline would FINALIZE may be held for review
    a report the existing pipeline would hold may NEVER be finalized

That is the acceptance condition, and these tests make it an invariant rather
than an intention. The last one checks it over every combination of modes and
service answers, including answers the code has never seen.

The second property is availability. A second reader that can make a report
unprocessable is not a second reader, it is a new dependency - so every
failure, from a timeout to a malformed response to a missing credential,
produces "no opinion" and the pipeline continues exactly as it would have.
"""
from __future__ import annotations

import itertools

import pytest

from apps.common.enums import ReportProcessingState, ValidationStatus
from apps.reports import second_reader
from apps.reports.pipeline import ReportPipeline
from apps.reports.second_reader import SecondOpinion

pytestmark = pytest.mark.django_db

#: The shape tests/integration/test_report_pipeline.py already proves
#: finalizes, so a failure here is about the second reader and nothing else.
CLEAN_GLUCOSE = """
CHEMISTRY
Collected: 2024-05-01 09:00
Reported: 2024-05-01 15:00
Glucose: 5.4 mmol/L
"""

INCOMPLETE_LIPID = """
LIPID PANEL
Collected: 2024-06-01 08:00
Total Cholesterol: 4.2 mmol/L
HDL Cholesterol: 1.3 mmol/L
LDL Cholesterol: 2.4 mmol/L
"""


class _FakeResult:
    def __init__(self, *, disposition="EXTRACTED", issues=None, values=None,
                 report_type="CBC", completeness=None, text_source="EMBEDDED_TEXT_LAYER"):
        self.disposition = disposition
        self.issues = issues or []
        self.values = values or []
        self.report_type = report_type
        self.completeness = completeness or {"outcome": "COMPLETE"}
        self.text_source = text_source


class _FakeClient:
    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls: list[dict] = []

    def process_document(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.result


def _upload(patient, uploader, text, *, hint):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.reports.services import ReportService

    handle = SimpleUploadedFile(
        "r.pdf", b"%PDF-1.4 test", content_type="application/pdf"
    )
    return ReportService().register_upload(
        patient=patient, uploaded_file=handle, uploaded_by=uploader,
        class_hint=hint, extracted_text=text,
    )


@pytest.fixture
def report(make_patient, make_user):
    from apps.common.enums import ReportClass

    return _upload(
        make_patient(), make_user(), CLEAN_GLUCOSE, hint=ReportClass.GLUCOSE
    )


def _run(report):
    from apps.reports.models import Report

    return ReportPipeline().run(Report.objects.get(pk=report.pk))


# --- off: the default, and nothing changes ---------------------------
def test_the_default_mode_is_off(settings):
    assert second_reader.mode() == second_reader.OFF


def test_an_unknown_mode_falls_back_to_off(settings):
    """A typo in configuration must not silently enable a clinical path."""
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisroy"}
    assert second_reader.mode() == second_reader.OFF


def test_with_the_mode_off_the_service_is_not_called(settings, report):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "off"}
    client = _FakeClient(_FakeResult())

    opinion = second_reader.consult(report, b"x", client=client)
    assert client.calls == []
    assert opinion.consulted is False
    assert opinion.holds_report is False


# --- shadow: recorded, never acted on --------------------------------
def test_shadow_mode_calls_the_service_but_does_not_change_the_outcome(
    settings, report, monkeypatch
):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "shadow"}
    concerned = _FakeResult(
        disposition="NEEDS_REVIEW",
        issues=[{"code": "VALUES_CONFLICTING", "severity": "HIGH", "detail": "hemoglobin"}],
    )
    monkeypatch.setattr(
        second_reader, "_default_client", lambda: _FakeClient(concerned)
    )

    result = _run(report)
    report.refresh_from_db()

    # The service was worried. The outcome is the existing pipeline's alone.
    assert report.processing_state == ReportProcessingState.FINALIZED
    assert result.ok


def test_shadow_mode_records_what_the_service_said(settings, report, monkeypatch):
    """The comparison that would justify going further is the whole point of
    running in shadow."""
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "shadow"}
    monkeypatch.setattr(
        second_reader, "_default_client",
        lambda: _FakeClient(_FakeResult(disposition="NEEDS_REVIEW")),
    )
    _run(report)

    from apps.audit import services as audit
    from apps.audit.models import AuditLog

    event = AuditLog.objects.filter(action=audit.REPORT_PROCESSED).latest("created_at")
    recorded = event.metadata["second_reader"]
    assert recorded["consulted"] is True
    assert recorded["available"] is True
    assert recorded["disposition"] == "NEEDS_REVIEW"
    assert recorded["concerns"]


# --- advisory: may hold, may never release ---------------------------
def test_advisory_mode_holds_a_report_the_service_is_worried_about(
    settings, report, monkeypatch
):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
    monkeypatch.setattr(
        second_reader, "_default_client",
        lambda: _FakeClient(_FakeResult(
            disposition="NEEDS_REVIEW",
            values=[{"analyte": "hemoglobin", "status": "CONFLICTING"}],
        )),
    )

    result = _run(report)
    report.refresh_from_db()

    assert report.processing_state == ReportProcessingState.REVIEW_REQUIRED
    assert report.validation_status == ValidationStatus.REVIEW_REQUIRED
    assert "second reading" in report.review_reason
    assert not result.ok


def test_advisory_mode_leaves_a_clean_report_alone(settings, report, monkeypatch):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
    monkeypatch.setattr(
        second_reader, "_default_client", lambda: _FakeClient(_FakeResult())
    )

    result = _run(report)
    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.FINALIZED
    assert result.ok


def test_the_second_reader_never_writes_a_clinical_value(
    settings, report, monkeypatch
):
    """It can say 'a person should look at this'. It cannot say what the
    haemoglobin is."""
    from apps.reports.models import ReportTest

    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
    monkeypatch.setattr(
        second_reader, "_default_client",
        lambda: _FakeClient(_FakeResult(values=[
            {"analyte": "glucose", "status": "OBSERVED",
             "value": 99.9, "persists_clinical_value": True},
            {"analyte": "ferritin", "status": "OBSERVED",
             "value": 12.0, "persists_clinical_value": True},
        ])),
    )
    _run(report)

    names = set(ReportTest.objects.filter(report=report).values_list("name", flat=True))
    assert "ferritin" not in names, "the service invented an analyte into the record"
    glucose = ReportTest.objects.get(report=report, name="glucose")
    assert float(glucose.value_normalized) == 5.4


# --- availability is never a clinical dependency ---------------------
@pytest.mark.parametrize("failure", [
    ConnectionError("service is down"),
    TimeoutError("took too long"),
    ValueError("malformed response"),
    RuntimeError("something nobody anticipated"),
])
def test_a_service_failure_is_no_opinion_not_a_blocked_report(
    settings, report, monkeypatch, failure
):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
    monkeypatch.setattr(
        second_reader, "_default_client", lambda: _FakeClient(raises=failure)
    )

    result = _run(report)
    report.refresh_from_db()

    assert report.processing_state == ReportProcessingState.FINALIZED
    assert result.ok


def test_a_failure_is_recorded_so_the_silence_is_visible(
    settings, report, monkeypatch
):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
    monkeypatch.setattr(
        second_reader, "_default_client",
        lambda: _FakeClient(raises=ConnectionError("service is down")),
    )
    _run(report)

    from apps.audit import services as audit
    from apps.audit.models import AuditLog

    event = AuditLog.objects.filter(action=audit.REPORT_PROCESSED).latest("created_at")
    recorded = event.metadata["second_reader"]
    assert recorded["available"] is False
    assert "ConnectionError" in recorded["unavailable_reason"]


def test_a_missing_credential_does_not_block_a_report(settings, report):
    """The client refuses to call without a token, which is correct. A report
    must not become unprocessable because of it."""
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
    settings.INTELLIGENCE = {**settings.INTELLIGENCE, "SERVICE_TOKEN": ""}

    result = _run(report)
    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.FINALIZED
    assert result.ok


# --- the boundary Django is responsible for --------------------------
def test_the_service_receives_content_and_never_a_path_or_a_patient(
    settings, report
):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
    client = _FakeClient(_FakeResult())
    second_reader.consult(report, CLEAN_GLUCOSE.encode(), client=client)

    sent = client.calls[0]
    assert sent["content"] == CLEAN_GLUCOSE.encode()
    assert str(report.patient.public_id) not in str(sent)
    for forbidden in ("path", "file_path", "storage_key", "patient_id", "url"):
        assert forbidden not in sent


def test_the_document_id_sent_is_the_reports_public_id(settings, report):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
    client = _FakeClient(_FakeResult())
    second_reader.consult(report, b"x", client=client)
    assert client.calls[0]["document_id"] == str(report.public_id)


def test_apps_reports_never_imports_the_document_package():
    """Django talks to the service over HTTP. Importing it would put the
    parser in the web process and quietly delete the boundary."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "apps" / "reports"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith("intelligence."), (
                    f"{path.name} imports {name}; Django reaches the service "
                    f"over HTTP and never in-process"
                )


# --- the invariant, over every combination ---------------------------
_ANSWERS = {
    "clean": _FakeResult(),
    "needs_review": _FakeResult(disposition="NEEDS_REVIEW"),
    "unreadable": _FakeResult(disposition="UNREADABLE"),
    "rejected": _FakeResult(disposition="REJECTED_FILE"),
    "high_issue": _FakeResult(issues=[{"code": "X", "severity": "HIGH", "detail": "d"}]),
    "low_issue": _FakeResult(issues=[{"code": "X", "severity": "LOW", "detail": "d"}]),
    "conflicting_value": _FakeResult(values=[{"analyte": "hemoglobin",
                                              "status": "CONFLICTING"}]),
    "ambiguous_value": _FakeResult(values=[{"analyte": "hemoglobin",
                                            "status": "AMBIGUOUS"}]),
    "unknown_disposition": _FakeResult(disposition="SOMETHING_NEW"),
}


@pytest.mark.parametrize(
    "mode,answer",
    list(itertools.product(["off", "shadow", "advisory"], sorted(_ANSWERS))),
)
def test_a_report_that_would_be_held_is_never_released_by_a_second_reading(
    settings, make_patient, make_lab_tech, monkeypatch, mode, answer
):
    """The half of the acceptance condition that matters most. Whatever the
    service says, and in whatever mode, it cannot turn a review into a pass."""
    from apps.common.enums import ReportClass
    from apps.reports.models import Report

    row = Report.objects.get(pk=_upload(
        make_patient(), make_lab_tech().user, INCOMPLETE_LIPID,
        hint=ReportClass.LIPID,
    ).pk)

    settings.DOCUMENT_INTELLIGENCE = {"MODE": mode}
    monkeypatch.setattr(
        second_reader, "_default_client", lambda: _FakeClient(_ANSWERS[answer])
    )

    _run(row)
    row.refresh_from_db()
    assert row.processing_state == ReportProcessingState.REVIEW_REQUIRED


@pytest.mark.parametrize("answer", sorted(_ANSWERS))
def test_shadow_mode_never_changes_the_outcome_whatever_the_service_says(
    settings, report, monkeypatch, answer
):
    settings.DOCUMENT_INTELLIGENCE = {"MODE": "shadow"}
    monkeypatch.setattr(
        second_reader, "_default_client", lambda: _FakeClient(_ANSWERS[answer])
    )

    _run(report)
    report.refresh_from_db()
    assert report.processing_state == ReportProcessingState.FINALIZED


@pytest.mark.parametrize("answer", ["clean", "low_issue", "ambiguous_value",
                                    "unknown_disposition"])
def test_an_answer_that_raises_no_concern_does_not_hold_a_report(answer):
    """A disposition this code has never heard of must not silently hold a
    report either - the holding set is named, not inferred."""
    opinion = second_reader._read(_ANSWERS[answer])
    assert opinion.holds_report is False


@pytest.mark.parametrize("answer", ["needs_review", "unreadable", "rejected",
                                    "high_issue", "conflicting_value"])
def test_the_answers_that_do_raise_a_concern_say_why(answer):
    opinion = second_reader._read(_ANSWERS[answer])
    assert opinion.holds_report is True
    assert all(concern.strip() for concern in opinion.concerns)


def test_an_opinion_with_no_service_available_never_holds():
    assert SecondOpinion(consulted=True, available=False,
                         concerns=["something"]).holds_report is False
