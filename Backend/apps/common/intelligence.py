"""Client for the FastAPI intelligence service.

Django is the ONLY caller of the intelligence service (spec sections 3, 52).
This client:

* sends only a validated feature payload plus a model/task identifier and the
  request correlation id - never raw database identifiers the service could
  use to fetch records itself;
* authenticates with a shared service token;
* fails closed - a transport error or non-2xx response raises
  :class:`UpstreamUnavailable`, it never fabricates a result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.common.errors import UpstreamUnavailable


@dataclass(frozen=True, slots=True)
class InferenceResult:
    raw_score: float | None
    calibrated_score: float | None
    calibration_version: str
    reliability_status: str
    reliability_detail: dict[str, Any]
    shap: list[dict[str, Any]]
    model_echo: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AiAnswerResult:
    status: str
    answer: str
    sections: dict[str, Any]
    used_knowledge: list[str]
    context_refs_used: list[str]
    flags: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DocumentProcessResult:
    """The intelligence service's structured read of a document.

    Every field here is advisory. Django decides what, if anything, becomes an
    authoritative record and which workflow opens - see
    :mod:`apps.reports.pipeline`. ``disposition`` is one of EXTRACTED /
    NEEDS_REVIEW / UNREADABLE / REJECTED_FILE.
    """

    document_id: str
    disposition: str
    source_sha256: str
    media_type: str
    text_source: str
    ocr_outcome: str | None
    classification: dict[str, Any] | None
    report_type: str | None
    values: list[dict[str, Any]]
    completeness: dict[str, Any] | None
    issues: list[dict[str, Any]]
    capabilities: dict[str, Any]
    notes: list[str]
    #: Results the service says it could see but did not extract, because it
    #: could not name the report type. A count only.
    values_forgone: int = 0
    #: Present only when ``detect_findings`` was requested and values were read.
    findings: dict[str, Any] | None = None

    @property
    def needs_human_review(self) -> bool:
        return self.disposition != "EXTRACTED" or any(
            issue.get("severity") == "HIGH" for issue in self.issues
        )


class IntelligenceClient:
    def __init__(self, *, base_url: str | None = None, token: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (base_url or settings.INTELLIGENCE["BASE_URL"]).rstrip("/")
        self.token = token or settings.INTELLIGENCE["SERVICE_TOKEN"]
        if not self.token:
            # Sending an empty credential is not a degraded mode, it is an
            # unauthenticated call to a service that holds the models. Fail
            # here, where the cause is obvious, rather than at the boundary.
            raise ImproperlyConfigured(
                "INTELLIGENCE_SERVICE_TOKEN is not set; refusing to call the "
                "intelligence service without a credential."
            )
        self.timeout = timeout or settings.INTELLIGENCE["TIMEOUT_SECONDS"]

    def _post(self, path: str, body: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
        import httpx

        headers = {
            "X-Service-Token": self.token,
            "X-Correlation-Id": correlation_id,
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                f"{self.base_url}{path}", json=body, headers=headers, timeout=self.timeout
            )
        except httpx.HTTPError as exc:  # pragma: no cover - network failure path
            raise UpstreamUnavailable(
                "The intelligence service could not be reached.",
                details={"path": path},
            ) from exc
        if response.status_code >= 500:
            raise UpstreamUnavailable(
                "The intelligence service reported an internal error.",
                details={"path": path, "status": response.status_code},
            )
        if response.status_code >= 400:
            raise UpstreamUnavailable(
                "The intelligence service rejected the request.",
                details={"path": path, "status": response.status_code},
            )
        return response.json()

    def infer(
        self,
        *,
        task: str,
        model_version: str,
        feature_schema_version: str,
        features: dict[str, Any],
        correlation_id: str,
    ) -> InferenceResult:
        data = self._post(
            "/v1/infer",
            {
                "task": task,
                "model_version": model_version,
                "feature_schema_version": feature_schema_version,
                "features": features,
                "correlation_id": correlation_id,
            },
            correlation_id=correlation_id,
        )
        return InferenceResult(
            raw_score=data.get("raw_score"),
            calibrated_score=data.get("calibrated_score"),
            calibration_version=data.get("calibration_version", ""),
            reliability_status=data.get("reliability", {}).get("status", "REVIEW_REQUIRED"),
            reliability_detail=data.get("reliability", {}),
            shap=data.get("shap", []),
            model_echo=data.get("model", {}),
        )

    def process_document(
        self,
        *,
        document_id: str,
        content: bytes,
        declared_media_type: str,
        correlation_id: str,
        document_type_hint: str = "",
        operations: list[str] | None = None,
        patient_sex: str = "",
        patient_age_years: float | None = None,
    ) -> DocumentProcessResult:
        """Send authorized document *content* for structured extraction.

        The service receives the bytes Django has already resolved and
        authorized - never a storage path or a patient id it could use to
        fetch something itself (spec section 52). It returns a structured
        result; the caller decides what to persist.
        """
        import base64

        body: dict[str, Any] = {
            "document_id": document_id,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "declared_media_type": declared_media_type,
            "document_type_hint": document_type_hint,
            "correlation_id": correlation_id,
        }
        if operations is not None:
            body["requested_operations"] = operations
        # Attributes for choosing a reference interval, never identifiers.
        if patient_sex:
            body["patient_sex"] = patient_sex
        if patient_age_years is not None:
            body["patient_age_years"] = patient_age_years

        data = self._post(
            "/v1/documents/process", body, correlation_id=correlation_id
        )
        return DocumentProcessResult(
            document_id=data.get("document_id", document_id),
            disposition=data.get("disposition", "UNREADABLE"),
            source_sha256=data.get("source_sha256", ""),
            media_type=data.get("media_type", ""),
            text_source=data.get("text_source", "NONE"),
            ocr_outcome=data.get("ocr_outcome"),
            classification=data.get("classification"),
            report_type=data.get("report_type"),
            values=data.get("values", []),
            completeness=data.get("completeness"),
            issues=data.get("issues", []),
            capabilities=data.get("capabilities", {}),
            notes=data.get("notes", []),
            values_forgone=int(data.get("values_forgone") or 0),
            findings=data.get("findings"),
        )

    def document_capabilities(self, *, correlation_id: str) -> dict[str, Any]:
        return self._post_get(
            "/v1/documents/capabilities", correlation_id=correlation_id
        )

    def _post_get(self, path: str, *, correlation_id: str) -> dict[str, Any]:
        """A GET that carries the service headers the boundary requires."""
        import httpx

        headers = {
            "X-Service-Token": self.token,
            "X-Correlation-Id": correlation_id,
        }
        try:
            response = httpx.get(
                f"{self.base_url}{path}", headers=headers, timeout=self.timeout
            )
        except httpx.HTTPError as exc:  # pragma: no cover - network failure path
            raise UpstreamUnavailable(
                "The intelligence service could not be reached.",
                details={"path": path},
            ) from exc
        if response.status_code >= 400:
            raise UpstreamUnavailable(
                "The intelligence service rejected the request.",
                details={"path": path, "status": response.status_code},
            )
        return response.json()

    def ai_answer(
        self,
        *,
        kind: str,
        question: str,
        context_blocks: list[dict[str, Any]],
        knowledge: list[dict[str, Any]],
        correlation_id: str,
    ) -> AiAnswerResult:
        data = self._post(
            "/v1/ai/answer",
            {
                "kind": kind,
                "question": question,
                "context_blocks": context_blocks,
                "knowledge": knowledge,
                "correlation_id": correlation_id,
            },
            correlation_id=correlation_id,
        )
        return AiAnswerResult(
            status=data.get("status", "INSUFFICIENT_CONTEXT"),
            answer=data.get("answer", ""),
            sections=data.get("sections", {}),
            used_knowledge=data.get("used_knowledge", []),
            context_refs_used=data.get("context_refs_used", []),
            flags=data.get("flags", {}),
        )
