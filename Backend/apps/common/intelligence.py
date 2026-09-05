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
