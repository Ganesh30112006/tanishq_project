from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.accounts.views import UserAdminViewSet

router = DefaultRouter()
router.register("", UserAdminViewSet, basename="user")

urlpatterns = router.urls
