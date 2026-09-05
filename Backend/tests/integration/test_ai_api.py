"""AI assistant API: authorization, patient-scope isolation, minimized context,
recorded + validated output, safe non-answer (spec sections 36-38, 54)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ai.models import AiInteraction
from apps.audit.models import AuditLog
from apps.common.enums import ClinicalDataState, Role
from apps.common.intelligence import AiAnswerResult
from apps.laboratories.models import Laboratory, LabOrder, LabResult

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def local_ai(monkeypatch):
    """Run the real deterministic summarizer in-process instead of over HTTP."""

    def _answer(self, *, kind, question, context_blocks, knowledge, correlation_id):
        from intelligence.rag.schemas import AiAnswerRequest
        from intelligence.rag.summarizer import summarize

        resp = summarize(
            AiAnswerRequest(
                kind=kind, question=question, context_blocks=context_blocks,
                knowledge=knowledge, correlation_id=correlation_id,
            )
        )
        return AiAnswerResult(
            status=resp.status, answer=resp.answer, sections=resp.sections.model_dump(),
            used_knowledge=resp.used_knowledge, context_refs_used=resp.context_refs_used,
            flags=resp.flags.model_dump(),
        )

    monkeypatch.setattr("apps.common.intelligence.IntelligenceClient.ai_answer", _answer)


def _glucose(patient, value="5.4"):
    lab = Laboratory.objects.create(name="L", code=f"L{patient.pk}")
    order = LabOrder.objects.create(laboratory=lab, patient=patient, panel="GLUCOSE")
    return LabResult.objects.create(
        order=order, analyte="glucose", value_normalized=Decimal(value), unit_normalized="mmol/L",
        state=ClinicalDataState.OBSERVED, observed_at=timezone.now(),
    )


def _ask(client, patient, question="What is the latest glucose?", kind="HISTORY_SUMMARY"):
    return client.post(
        "/api/v1/ai/ask",
        {"patient_id": str(patient.public_id), "kind": kind, "question": question},
        format="json",
    )


def test_doctor_gets_recorded_answer_over_authorized_minimized_context(
    auth_client, make_doctor, make_patient, assign_patient
):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    _glucose(patient)

    resp = _ask(auth_client(doctor.user), patient)
    assert resp.status_code == 201
    assert resp.data["status"] == "COMPLETED"
    assert "OBSERVED DATA:" in resp.data["output_text"]
    assert "5.4 mmol/L" in resp.data["output_text"]
    assert resp.data["context_refs"]  # references, not raw record contents
    assert resp.data["output_flags"]["invented_facts"] is False

    interaction = AiInteraction.objects.get()
    assert interaction.status == AiInteraction.Status.COMPLETED
    assert interaction.patient_id == patient.pk
    assert AuditLog.objects.filter(action="ai.interaction", result="SUCCESS").exists()


def test_cross_patient_request_is_not_found(auth_client, make_doctor, make_patient):
    doctor = make_doctor()
    other = make_patient()
    _glucose(other)
    resp = _ask(auth_client(doctor.user), other)
    assert resp.status_code == 404
    assert not AiInteraction.objects.exists()


def test_patient_role_cannot_use_the_assistant(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    _glucose(patient)
    resp = _ask(auth_client(alice), patient)
    assert resp.status_code == 403
    assert resp.data["error"]["code"] == "ACCESS_DENIED"


def test_no_authorized_context_is_a_safe_non_answer(
    auth_client, make_doctor, make_patient, assign_patient
):
    doctor = make_doctor()
    patient = make_patient()  # no clinical data at all
    assign_patient(doctor, patient)

    resp = _ask(auth_client(doctor.user), patient)
    assert resp.status_code == 200
    assert resp.data["status"] == "blocked"
    assert resp.data["outcome"] == "INSUFFICIENT_DATA"
    interaction = AiInteraction.objects.get()
    assert interaction.status == AiInteraction.Status.BLOCKED
    assert interaction.output_flags.get("invented_facts") is False


def test_patient_reads_only_their_own_interactions(
    auth_client, make_user, make_patient, make_doctor, assign_patient
):
    alice = make_user(Role.PATIENT)
    alice_patient = make_patient(user=alice)
    AiInteraction.objects.create(patient=alice_patient, kind="QA", status="COMPLETED")
    AiInteraction.objects.create(patient=make_patient(), kind="QA", status="COMPLETED")

    resp = auth_client(alice).get("/api/v1/ai/interactions/")
    assert resp.status_code == 200
    ids = {row["patient_id"] for row in resp.data["results"]}
    assert ids == {str(alice_patient.public_id)}


def test_approved_knowledge_is_listable(auth_client, make_doctor):
    resp = auth_client(make_doctor().user).get("/api/v1/ai/knowledge/")
    assert resp.status_code == 200
    assert resp.data["count"] >= 3
    assert all("body" in row for row in resp.data["results"])
