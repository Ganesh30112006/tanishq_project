"""ISSUE-002 regression: report types for every kind of report.

The existing pipeline's keyword vote types only four panels, so a thyroid,
liver, kidney or any other report was shown to the patient as "Other". The AI
reader's classifier knows every ``ReportClass``. Its type is recorded on the
analysis and shown where the pipeline could not tell - without touching
``Report.report_class``, which still picks the schema and finds duplicates.
"""
from __future__ import annotations

import pytest

from apps.common.enums import ReportClass, Role
from apps.reports import analysis
from apps.reports.models import Report, ReportAnalysis
from tests.integration.test_report_analysis import (
    _FakeClient,
    _FakeResult,
    _upload,
    _value,
)

pytestmark = pytest.mark.django_db

#: Every type the AI reader can name. OTHER is "could not tell", not a type.
EVERY_TYPE = [code for code in ReportClass.values if code != ReportClass.OTHER]


def _classified(report_type, *, status="CLASSIFIED"):
    result = _FakeResult(values=[_value("tsh", 8.2, "mIU/L")])
    result.classification = {"type": report_type, "status": status, "reason": ""}
    result.report_type = report_type if status == "CLASSIFIED" else None
    return result


def _untyped_report(patient, uploader):
    report = _upload(patient, uploader)
    # What the existing pipeline leaves on a panel its vote does not know.
    Report.objects.filter(pk=report.pk).update(report_class=ReportClass.OTHER, class_hint="")
    report.refresh_from_db()
    return report


def _listed(client, report):
    resp = client.get("/api/v1/reports/", {"patient_id": str(report.patient.public_id)})
    assert resp.status_code == 200
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    return next(r for r in rows if r["id"] == str(report.public_id))


@pytest.mark.parametrize("report_type", EVERY_TYPE)
def test_every_type_the_ai_names_is_recorded_and_shown(
    report_type, make_user, make_patient, auth_client
):
    user = make_user(Role.PATIENT)
    report = _untyped_report(make_patient(user=user), user)

    stored = analysis.analyse(report, client=_FakeClient(_classified(report_type)))

    assert stored.report_type == report_type
    row = _listed(auth_client(user), report)
    assert row["report_class"] == ReportClass.OTHER  # the pipeline's own answer stands
    assert row["ai_report_class"] == report_type
    assert row["title"] == "r.pdf"
    resp = auth_client(user).get(f"/api/v1/reports/{report.public_id}/analysis/")
    assert resp.json()["report_type"] == report_type


def test_an_abstaining_classifier_names_no_type(make_user, make_patient):
    user = make_user(Role.PATIENT)
    report = _untyped_report(make_patient(user=user), user)

    stored = analysis.analyse(
        report, client=_FakeClient(_classified("THYROID", status="REVIEW_REQUIRED"))
    )

    assert stored.report_type == ""


def test_a_type_django_does_not_know_is_dropped(make_user, make_patient):
    user = make_user(Role.PATIENT)
    report = _untyped_report(make_patient(user=user), user)

    stored = analysis.analyse(report, client=_FakeClient(_classified("ECHOCARDIOGRAM")))

    assert stored.report_type == ""


def test_a_service_that_predates_classification_names_no_type(make_user, make_patient):
    user = make_user(Role.PATIENT)
    report = _untyped_report(make_patient(user=user), user)

    stored = analysis.analyse(report, client=_FakeClient(_FakeResult(values=[_value("tsh", 8.2, "mIU/L")])))

    assert stored.status == ReportAnalysis.Status.READY
    assert stored.report_type == ""


def test_the_pipelines_type_wins_where_it_named_one(make_user, make_patient, auth_client):
    user = make_user(Role.PATIENT)
    report = _upload(make_patient(user=user), user)  # uploaded as GLUCOSE
    Report.objects.filter(pk=report.pk).update(report_class=ReportClass.GLUCOSE)

    analysis.analyse(report, client=_FakeClient(_classified("THYROID")))

    report.refresh_from_db()
    assert report.report_class == ReportClass.GLUCOSE
    assert _listed(auth_client(user), report)["ai_report_class"] is None


def test_an_analysis_of_an_older_version_is_not_shown(make_user, make_patient, auth_client):
    user = make_user(Role.PATIENT)
    report = _untyped_report(make_patient(user=user), user)
    analysis.analyse(report, client=_FakeClient(_classified("LIVER")))

    Report.objects.filter(pk=report.pk).update(version=report.version + 1)

    assert _listed(auth_client(user), report)["ai_report_class"] is None

