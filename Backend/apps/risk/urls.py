from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.risk.views import ModelVersionViewSet, RiskAssessmentViewSet

router = DefaultRouter()
router.register("assessments", RiskAssessmentViewSet, basename="risk-assessment")
router.register("models", ModelVersionViewSet, basename="risk-model")

urlpatterns = router.urls
