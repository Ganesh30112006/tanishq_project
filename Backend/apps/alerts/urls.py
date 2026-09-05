from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.alerts.views import AlertViewSet

router = DefaultRouter()
router.register("", AlertViewSet, basename="alert")

urlpatterns = router.urls
