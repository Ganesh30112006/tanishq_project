from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.appointments.views import (
    AppointmentViewSet,
    AvailabilityViewSet,
    DoctorDirectoryViewSet,
)

router = DefaultRouter()
router.register("availability", AvailabilityViewSet, basename="availability")
router.register("directory", DoctorDirectoryViewSet, basename="doctor-directory")
router.register("", AppointmentViewSet, basename="appointment")

urlpatterns = router.urls
