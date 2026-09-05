"""Structured clinical record API (spec sections 5, 42, 44).

Doctors author conditions / medications / symptoms / clinical notes for
assigned patients; patients and assigned doctors read. Clinical notes are
append-only - an ``addendum`` action amends without editing.
"""
from __future__ import annotations

from apps.accounts.permissions import (
    CLINICAL_NOTE_CREATE,
    RECORD_READ_ASSIGNED,
    RECORD_READ_OWN,
    PermissionResolver,
)
from apps.audit import services as audit
from apps.common.api import PatientScopedViewSet
from apps.common.errors import ResourceNotFound
from apps.medical_records.models import Allergy, ClinicalNote, Condition, Medication, Symptom
from apps.medical_records.serializers import (
    AllergySerializer,
    AllergyWriteSerializer,
    ClinicalNoteSerializer,
    ClinicalNoteWriteSerializer,
    ConditionSerializer,
    ConditionWriteSerializer,
    MedicationSerializer,
    MedicationWriteSerializer,
    SymptomSerializer,
    SymptomWriteSerializer,
)
from apps.medical_records.services import ClinicalNoteService

_READ_PERMS = (RECORD_READ_OWN, RECORD_READ_ASSIGNED)


class _RecordViewSet(PatientScopedViewSet):
    def get_queryset(self):
        if not PermissionResolver.has_any(self.request.user, *_READ_PERMS):
            return self.model.objects.none()
        return super().get_queryset()


class ConditionViewSet(_RecordViewSet):
    model = Condition
    serializer_class = ConditionSerializer
    write_serializer_class = ConditionWriteSerializer


class MedicationViewSet(_RecordViewSet):
    model = Medication
    serializer_class = MedicationSerializer
    write_serializer_class = MedicationWriteSerializer


class AllergyViewSet(_RecordViewSet):
    model = Allergy
    serializer_class = AllergySerializer
    write_serializer_class = AllergyWriteSerializer


class SymptomViewSet(_RecordViewSet):
    model = Symptom
    serializer_class = SymptomSerializer
    write_serializer_class = SymptomWriteSerializer
    order_by = "-reported_at"


class ClinicalNoteViewSet(_RecordViewSet):
    model = ClinicalNote
    serializer_class = ClinicalNoteSerializer
    write_serializer_class = ClinicalNoteWriteSerializer
    select_related = ("author", "amends", "patient")
    order_by = "-authored_at"
    audit_action = audit.RECORD_MODIFY

    def perform_scoped_create(self, data: dict, patient, actor):
        PermissionResolver.require(actor, CLINICAL_NOTE_CREATE)
        amends = None
        if data.get("amends_id"):
            amends = ClinicalNote.objects.filter(
                patient=patient, public_id=data["amends_id"]
            ).first()
            if amends is None:
                raise ResourceNotFound("The note to amend was not found for this patient.")
        service = ClinicalNoteService()
        if amends is not None:
            return service.add_addendum(original=amends, author=actor, body=data["body"])
        return service.add_note(
            patient=patient, author=actor, body=data["body"],
            note_type=data.get("note_type", ClinicalNote.NoteType.PROGRESS),
        )
