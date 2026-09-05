from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.notifications.views import MissingDataTaskViewSet, NotificationViewSet

router = DefaultRouter()
# Register the specific prefix before the catch-all so it resolves first.
router.register("tasks", MissingDataTaskViewSet, basename="missing-data-task")
router.register("", NotificationViewSet, basename="notification")

urlpatterns = router.urls
