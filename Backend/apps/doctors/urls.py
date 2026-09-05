from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.doctors.admin_api import AssignmentAdminViewSet, DoctorAdminViewSet
from apps.doctors.views import MyAssignmentViewSet

router = DefaultRouter()
router.register("assignments", MyAssignmentViewSet, basename="doctor-assignment")
router.register("profiles", DoctorAdminViewSet, basename="doctor-profile")
router.register("admin/assignments", AssignmentAdminViewSet, basename="assignment-admin")

urlpatterns = router.urls
