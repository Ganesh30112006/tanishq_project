"""Report processing services (spec sections 11-16, 39).

Only the intake stage is implemented in this foundation drop:
:meth:`ReportService.register_upload` validates the untrusted file, stores it
privately, records its hash, and enqueues a processing job. The later stages
(OCR, classification, section/entity extraction, normalization, deterministic
validation, completeness analysis, provenance, reconciliation, human review)
are the report-pipeline slice and currently return a safe
``REVIEW_REQUIRED`` outcome rather than guessing.
"""
from __future__ import annotations

import hashlib
import os

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import ReportProcessingState, ValidationStatus
from apps.common.errors import ValidationFailed
from apps.common.services import BaseService, ServiceResult
from apps.patients.models import Patient
from apps.reports.models import Report


class ReportService(BaseService):
    @transaction.atomic
    def register_upload(
        self,
        *,
        patient: Patient,
        uploaded_file: UploadedFile,
        uploaded_by,
        class_hint: str = "",
        extracted_text: str = "",
    ) -> Report:
        cfg = settings.REPORT_UPLOAD
        self._validate_file(uploaded_file, cfg)

        digest = hashlib.sha256()
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
        uploaded_file.seek(0)
        sha256 = digest.hexdigest()

        report = Report(
            patient=patient,
            uploaded_by=uploaded_by,
            processing_state=ReportProcessingState.RECEIVED,
            validation_status=ValidationStatus.PENDING,
            class_hint=class_hint or "",
            extracted_text=extracted_text or "",
            original_filename=os.path.basename(uploaded_file.name)[:255],
            file_sha256=sha256,
            file_content_type=(uploaded_file.content_type or "")[:100],
            file_size=uploaded_file.size or 0,
        )
        report.source_file = uploaded_file
        report.full_clean(exclude=["schema", "uploaded_by"])
        report.save()

        # Background processing - never block the request on OCR/ML (section 47).
        from apps.jobs.services import JobService

        JobService().enqueue(
            "reports.process",
            payload={"report_id": str(report.public_id)},
            idempotency_key=f"reports.process:{report.public_id}",
        )

        audit_service.record(
            audit.REPORT_UPLOAD,
            actor=uploaded_by,
            resource=report,
            metadata={"sha256": sha256, "size": report.file_size},
        )
        return report

    @staticmethod
    def _validate_file(uploaded_file: UploadedFile, cfg: dict) -> None:
        if (uploaded_file.size or 0) > cfg["MAX_BYTES"]:
            raise ValidationFailed("The uploaded file exceeds the maximum permitted size.")
        ext = os.path.splitext(uploaded_file.name or "")[1].lower()
        if ext not in cfg["ALLOWED_EXTENSIONS"]:
            raise ValidationFailed(f"File extension '{ext}' is not permitted.")
        if (uploaded_file.content_type or "") not in cfg["ALLOWED_CONTENT_TYPES"]:
            raise ValidationFailed(
                f"Content type '{uploaded_file.content_type}' is not permitted."
            )
        ReportService._scan(uploaded_file)

    @staticmethod
    def _scan(uploaded_file: UploadedFile) -> None:
        """Inspect the bytes of an untrusted upload (spec section 39).

        Two layers, and the first cannot be switched off. The built-in content
        gate always runs: it checks that the file really is the document type
        it claims and carries no active content. This used to be a no-op unless
        an operator configured a scanner, which meant a deployment that simply
        forgot the setting accepted anything at all - the same fail-open shape
        as an unset service token.

        ``REPORT_UPLOAD_SCANNER`` then adds a real antivirus engine on top.
        It is optional in development and required in production, where
        ``config.settings.prod`` refuses to start without it.
        """
        from apps.reports.scanning import scan as builtin_scan

        builtin_scan(uploaded_file)
        uploaded_file.seek(0)

        target = getattr(settings, "REPORT_UPLOAD_SCANNER", "")
        if not target:
            return
        module_path, _, attr = target.partition(":")
        import importlib

        scanner = getattr(importlib.import_module(module_path), attr)
        scanner(uploaded_file)
        uploaded_file.seek(0)

    def run_pipeline(self, report: Report) -> ServiceResult:
        """Run the deterministic report-processing pipeline synchronously.
        Normally invoked via the ``reports.process`` background job."""
        from apps.reports.pipeline import ReportPipeline

        return ReportPipeline().run(report)
