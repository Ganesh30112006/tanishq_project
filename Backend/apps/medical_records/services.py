from __future__ import annotations

from django.db import transaction

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.services import BaseService
from apps.medical_records.models import ClinicalNote, Provenance
from apps.patients.models import Patient


class ClinicalNoteService(BaseService):
    @transaction.atomic
    def add_note(
        self, *, patient: Patient, author, body: str, note_type: str = ClinicalNote.NoteType.PROGRESS
    ) -> ClinicalNote:
        note = ClinicalNote.objects.create(
            patient=patient, author=author, body=body, note_type=note_type
        )
        audit_service.record(
            audit.RECORD_MODIFY, actor=author, resource=note, metadata={"change": "clinical_note.add"}
        )
        return note

    @transaction.atomic
    def add_addendum(self, *, original: ClinicalNote, author, body: str) -> ClinicalNote:
        return ClinicalNote.objects.create(
            patient=original.patient,
            author=author,
            body=body,
            note_type=ClinicalNote.NoteType.ADDENDUM,
            amends=original,
        )


class ProvenanceService(BaseService):
    """Provenance is written by the report pipeline and structured importers.
    Deeper extraction wiring belongs to the report-pipeline slice
    (spec sections 10-12)."""

    def record(self, **fields) -> Provenance:
        return Provenance.objects.create(**fields)
