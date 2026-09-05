from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.patients.identity_api import (
    PatientIdentityCandidateViewSet,
    PatientMergeRecordViewSet,
)
from apps.patients.views import PatientViewSet

router = DefaultRouter()
# Specific prefixes before the catch-all patient route.
router.register("identity/candidates", PatientIdentityCandidateViewSet, basename="identity-candidate")
router.register("identity/merges", PatientMergeRecordViewSet, basename="identity-merge")
router.register("", PatientViewSet, basename="patient")

urlpatterns = router.urls
