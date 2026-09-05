from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.health.views import HealthMeasurementViewSet

router = DefaultRouter()
router.register("measurements", HealthMeasurementViewSet, basename="health-measurement")

urlpatterns = router.urls
