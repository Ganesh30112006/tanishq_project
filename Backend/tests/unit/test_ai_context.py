from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ai.context import ContextAssembler
from apps.ai.models import AiInteraction
from apps.common.enums import (
    ClinicalDataState,
    ReportProcessingState,
    ValidationStatus,
)
from apps.laboratories.models import Laboratory, LabOrder, LabResult
from apps.medical_records.models import Condition
from apps.reports.models import Report, ReportTest

pytestmark = pytest.mark.django_db


def _glucose(patient, value="5.4"):
    lab = Laboratory.objects.create(name="L", code=f"L{patient.pk}")
    order = LabOrder.objects.create(laboratory=lab, patient=patient, panel="GLUCOSE")
    return LabResult.objects.create(
        order=order, analyte="glucose", value_normalized=Decimal(value), unit_normalized="mmol/L",
        state=ClinicalDataState.OBSERVED, observed_at=timezone.now(),
    )


def test_history_context_is_minimized_and_labelled(make_patient):
    patient = make_patient()
    _glucose(patient)
    Condition.objects.create(
        patient=patient, label="Type 2 diabetes",
        clinical_status=Condition.ClinicalStatus.ACTIVE,
    )

    ctx = ContextAssembler().assemble(patient=patient, kind=AiInteraction.Kind.HISTORY_SUMMARY)

    types = {b["type"] for b in ctx.blocks}
    assert types == {"lab_result", "condition"}
    assert all("state" in b for b in ctx.blocks)
    assert ctx.refs == [b["ref"] for b in ctx.blocks]
    # Approved general knowledge is attached, and it is not patient data.
    assert ctx.knowledge and all(set(d) == {"title", "body"} for d in ctx.knowledge)


def test_superseded_and_untrusted_lab_values_are_excluded(make_patient):
    patient = make_patient()
    lab = Laboratory.objects.create(name="L", code=f"L{patient.pk}")
    order = LabOrder.objects.create(laboratory=lab, patient=patient, panel="GLUCOSE")
    old = LabResult.objects.create(
        order=order, analyte="glucose", value_normalized=Decimal("9.9"), unit_normalized="mmol/L",
        state=ClinicalDataState.OBSERVED, observed_at=timezone.now(),
    )
    new = LabResult.objects.create(
        order=order, analyte="glucose", value_normalized=Decimal("5.4"), unit_normalized="mmol/L",
        state=ClinicalDataState.OBSERVED, observed_at=timezone.now(),
    )
    new.supersedes = old
    new.save(update_fields=["supersedes"])
    # An explicitly not-reported row must not appear either.
    LabResult.objects.create(
        order=order, analyte="hba1c", value_normalized=None,
        state=ClinicalDataState.NOT_REPORTED, observed_at=timezone.now(),
    )

    ctx = ContextAssembler().assemble(patient=patient, kind=AiInteraction.Kind.QA)
    lab_labels = [b["label"] for b in ctx.blocks if b["type"] == "lab_result"]
    assert lab_labels == ["glucose"]  # one row, the current one
    assert "hba1c" not in lab_labels


def test_report_summary_context_is_scoped_to_that_report(make_patient, make_user):
    patient = make_patient()
    _glucose(patient)  # history data that must NOT leak into a report summary
    report = Report.objects.create(
        patient=patient, uploaded_by=make_user(), report_class="HBA1C",
        processing_state=ReportProcessingState.FINALIZED, file_sha256="x", source_file="x.pdf",
    )
    ReportTest.objects.create(
        report=report, name="hba1c", value_normalized=Decimal("48"), unit_normalized="mmol/mol",
        state=ClinicalDataState.OBSERVED, validation_status=ValidationStatus.PASSED,
        extraction_method="OCR",
    )

    ctx = ContextAssembler().assemble(
        patient=patient, kind=AiInteraction.Kind.REPORT_SUMMARY, report=report
    )
    assert {b["type"] for b in ctx.blocks} == {"report_test"}
    assert ctx.blocks[0]["label"] == "hba1c"
