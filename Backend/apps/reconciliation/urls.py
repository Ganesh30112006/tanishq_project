from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.reconciliation.views import ReconciliationEventViewSet

router = DefaultRouter()
router.register("events", ReconciliationEventViewSet, basename="reconciliation-event")

urlpatterns = router.urls
