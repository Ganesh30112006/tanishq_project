"""Reports API (spec sections 11, 12, 39, 42, 48).

* ``POST /api/v1/reports/`` - upload an untrusted report file (patient for
  self, lab technician within an open workflow). The file is validated,
  stored privately, hashed, and a ``reports.process`` job is enqueued.
* ``GET /api/v1/reports/`` / ``/{id}/`` - scoped list/retrieve of the
  structured report (sections, tests, findings, provenance-backed).
* ``POST /api/v1/reports/{id}/reprocess`` - re-run the pipeline.
* ``GET /api/v1/reports/{id}/quality`` - data-quality metrics (NOT a health
  score).
* ``GET /api/v1/reports/{id}/file`` - stream the stored original (authorized;
  never via a client-supplied path).
"""
from __future__ import annotations

from django.http import FileResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import (
    LAB_REPORT_UPLOAD,
    LAB_WORKFLOW_ACCESS,
    REPORT_READ_ASSIGNED,
    REPORT_READ_OWN,
    REPORT_UPLOAD_OWN,
    PermissionResolver,
)
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.authz.drf import ResourceAccessPermission
from apps.authz.engine import Action, authorize
from apps.authz.relationships import visible_patient_queryset
from apps.common.enums import ValidationStatus
from apps.common.errors import AccessDenied, ResourceNotFound
from apps.jobs.services import JobService
from apps.reports.models import Report
from apps.reports.serializers import ReportSerializer, ReportUploadSerializer
from apps.reports.services import ReportService

_READ_PERMS = (REPORT_READ_OWN, REPORT_READ_ASSIGNED, LAB_WORKFLOW_ACCESS)
_UPLOAD_PERMS = (REPORT_UPLOAD_OWN, LAB_REPORT_UPLOAD)


class ReportViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated, ResourceAccessPermission]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ReportSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        user = self.request.user
        if not PermissionResolver.has_any(user, *_READ_PERMS):
            return Report.objects.none()
        patient_ids = visible_patient_queryset(user).values_list("pk", flat=True)
        qs = Report.objects.filter(patient_id__in=patient_ids)

        # A laboratory technician is in a patient's scope only for as long as an
        # order is open, and that is to process *their* laboratory's work. It is
        # not a key to the patient's whole document folder - a discharge
        # summary or a prescription the patient uploaded is none of their
        # business. Narrow them to what their own laboratory put there.
        if not PermissionResolver.has_any(user, REPORT_READ_OWN, REPORT_READ_ASSIGNED):
            from apps.laboratories.models import LabTechnician

            lab_ids = LabTechnician.objects.filter(
                user_id=user.pk, is_active=True
            ).values_list("laboratory_id", flat=True)
            colleagues = LabTechnician.objects.filter(
                laboratory_id__in=lab_ids
            ).values_list("user_id", flat=True)
            qs = qs.filter(uploaded_by_id__in=colleagues)

        patient_id = self.request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient__public_id=patient_id)
        report_status = self.request.query_params.get("status")
        if report_status:
            qs = qs.filter(processing_state=report_status)
        return (
            qs.select_related("patient", "schema", "uploaded_by")
            .prefetch_related("tests", "sections", "findings")
            .order_by("-created_at")
        )

    # -- upload -------------------------------------------------------
    def create(self, request: Request) -> Response:
        if not PermissionResolver.has_any(request.user, *_UPLOAD_PERMS):
            raise AccessDenied(details={"required_permission": list(_UPLOAD_PERMS)})

        payload = ReportUploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        patient = (
            visible_patient_queryset(request.user)
            .filter(public_id=payload.validated_data["patient_id"])
            .first()
        )
        if patient is None:
            raise ResourceNotFound("Patient not found or not accessible.")
        authorize(request.user, Action.CREATE, Report(patient=patient))

        report = ReportService().register_upload(
            patient=patient,
            uploaded_file=payload.validated_data["file"],
            uploaded_by=request.user,
            class_hint=payload.validated_data.get("class_hint", ""),
            extracted_text=payload.validated_data.get("extracted_text", ""),
        )
        return Response(ReportSerializer(report).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        audit_service.record(audit.REPORT_ACCESS, actor=request.user, resource=self.get_object())
        return response

    # -- reprocess --------------------------------------------------
    @action(detail=True, methods=["post"])
    def reprocess(self, request: Request, public_id=None) -> Response:
        report = self.get_object()
        authorize(request.user, Action.PROCESS, report)
        JobService().enqueue(
            "reports.process",
            payload={"report_id": str(report.public_id)},
            idempotency_key=f"reports.process:{report.public_id}:{report.version}",
        )
        return Response({"status": "queued"}, status=status.HTTP_202_ACCEPTED)

    # -- data quality (spec section 48) --------------------------
    @action(detail=True, methods=["get"])
    def quality(self, request: Request, public_id=None) -> Response:
        report = self.get_object()
        tests = list(report.tests.all())
        confidences = [
            float(x)
            for t in tests
            for x in (t.ocr_confidence, t.entity_confidence, t.context_confidence)
            if x is not None
        ]
        passed = [t for t in tests if t.validation_status == ValidationStatus.PASSED]
        missing_required = 0
        if report.schema:
            required = set(report.schema.definition.get("required_fields", []))
            present = {t.name for t in passed}
            missing_required = len(required - present)

        def grade(fraction: float) -> str:
            return "HIGH" if fraction >= 0.95 else "MEDIUM" if fraction >= 0.75 else "LOW"

        extraction_score = sum(confidences) / len(confidences) if confidences else 0.0
        return Response(
            {
                "report_id": str(report.public_id),
                "completeness": report.completeness_status or "UNKNOWN",
                "extraction_reliability": grade(extraction_score),
                "validation": "PASS" if tests and not (len(tests) - len(passed)) else "REVIEW",
                "consistency": "PASS"
                if report.processing_state != "REVIEW_REQUIRED" or "onflict" not in report.review_reason
                else "REVIEW",
                "required_fields_missing": missing_required,
                "tests_total": len(tests),
                "tests_validated": len(passed),
                "note": "Data-quality metric only; not a medical health score.",
            }
        )

    # -- original file ------------------------------------------
    @action(detail=True, methods=["get"])
    def file(self, request: Request, public_id=None):
        report = self.get_object()  # runs object-level authorization
        audit_service.record(
            audit.REPORT_ACCESS, actor=request.user, resource=report, metadata={"view": "file"}
        )
        handle = report.source_file.open("rb")
        # Serve the type the file was VERIFIED to be at upload, derived from its
        # extension - never the Content-Type the uploader declared. Echoing the
        # client's own header back is how a stored file becomes stored XSS: a
        # file accepted as a report and replayed as text/html executes in the
        # viewer's session. as_attachment already forces a download; this makes
        # the header itself untrusted-input-free as well.
        import os

        from apps.reports.scanning import content_type_for

        ext = os.path.splitext(report.original_filename or "")[1].lower()
        response = FileResponse(
            handle,
            content_type=content_type_for(ext),
            as_attachment=True,
            filename=report.original_filename or "report",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response
