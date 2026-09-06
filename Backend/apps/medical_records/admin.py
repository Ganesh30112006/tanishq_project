from __future__ import annotations

from django.contrib import admin

from apps.medical_records.models import (
    Allergy,
    ClinicalNote,
    Condition,
    MedicalHistory,
    Medication,
    Provenance,
    Symptom,
)

for _model in (Provenance, MedicalHistory, Condition, Medication, Allergy, Symptom, ClinicalNote):
    admin.site.register(_model)
