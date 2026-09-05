from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.medical_records.views import (
    AllergyViewSet,
    ClinicalNoteViewSet,
    ConditionViewSet,
    MedicationViewSet,
    SymptomViewSet,
)

router = DefaultRouter()
router.register("conditions", ConditionViewSet, basename="condition")
router.register("medications", MedicationViewSet, basename="medication")
router.register("allergies", AllergyViewSet, basename="allergy")
router.register("symptoms", SymptomViewSet, basename="symptom")
router.register("notes", ClinicalNoteViewSet, basename="clinical-note")

urlpatterns = router.urls
