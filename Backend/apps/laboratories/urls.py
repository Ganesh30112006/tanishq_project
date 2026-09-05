from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.laboratories.admin_api import LaboratoryViewSet, LabTechnicianViewSet
from apps.laboratories.views import LabOrderViewSet, LabResultViewSet

router = DefaultRouter()
router.register("orders", LabOrderViewSet, basename="lab-order")
router.register("results", LabResultViewSet, basename="lab-result")
router.register("laboratories", LaboratoryViewSet, basename="laboratory")
router.register("technicians", LabTechnicianViewSet, basename="lab-technician")

urlpatterns = router.urls
