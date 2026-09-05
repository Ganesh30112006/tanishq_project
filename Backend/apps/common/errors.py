"""Structured application errors and the DRF exception handler.

Every error returned to a client has the shape::

    {
      "error": {
        "code": "ACCESS_DENIED",
        "message": "You are not allowed to open this.",
        "details": {...},
        "request_id": "..."
      }
    }

Stack traces, SQL errors, internal paths and secrets are never returned
(spec section 43).
"""
from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler


class ErrorCode:
    """Canonical error codes (spec section 43). Strings, not an enum, so they
    serialize trivially and can be referenced from tests and clients."""

    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REPORT_UNREADABLE = "REPORT_UNREADABLE"
    REPORT_INCOMPLETE = "REPORT_INCOMPLETE"
    CONFLICTING_DATA = "CONFLICTING_DATA"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DATA_OUTDATED = "DATA_OUTDATED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_OUT_OF_DOMAIN = "MODEL_OUT_OF_DOMAIN"
    PREDICTION_BLOCKED = "PREDICTION_BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    ANALYSIS_COOLDOWN = "ANALYSIS_COOLDOWN"
    CONFLICT = "CONFLICT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base class for all deliberately-surfaced application errors."""

    code: str = ErrorCode.INTERNAL_ERROR
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        super().__init__(self.message)

    def to_payload(self, request_id: str | None = None) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": request_id,
            }
        }


class AuthenticationRequired(AppError):
    code = ErrorCode.AUTHENTICATION_REQUIRED
    http_status = status.HTTP_401_UNAUTHORIZED
    default_message = "Authentication is required."


class AccessDenied(AppError):
    code = ErrorCode.ACCESS_DENIED
    http_status = status.HTTP_403_FORBIDDEN
    default_message = "You are not allowed to open this."


class ResourceNotFound(AppError):
    code = ErrorCode.RESOURCE_NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND
    default_message = "The requested resource was not found."


class ValidationFailed(AppError):
    code = ErrorCode.VALIDATION_FAILED
    http_status = status.HTTP_400_BAD_REQUEST
    default_message = "The request failed validation."


class ReportUnreadable(AppError):
    code = ErrorCode.REPORT_UNREADABLE
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "The report could not be read."


class ReportIncomplete(AppError):
    code = ErrorCode.REPORT_INCOMPLETE
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "The report is missing required information."


class ConflictingData(AppError):
    code = ErrorCode.CONFLICTING_DATA
    http_status = status.HTTP_409_CONFLICT
    default_message = "Conflicting clinical values were found and must be reconciled."


class InsufficientData(AppError):
    code = ErrorCode.INSUFFICIENT_DATA
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "There is not enough valid data to complete this operation."


class DataOutdated(AppError):
    code = ErrorCode.DATA_OUTDATED
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "The available data is not recent enough for this operation."


class ModelUnavailable(AppError):
    code = ErrorCode.MODEL_UNAVAILABLE
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "The requested model is not available."


class ModelOutOfDomain(AppError):
    code = ErrorCode.MODEL_OUT_OF_DOMAIN
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "The input falls outside the model's validated domain."


class PredictionBlocked(AppError):
    code = ErrorCode.PREDICTION_BLOCKED
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "The prediction was blocked as a safe outcome."


class ReviewRequired(AppError):
    code = ErrorCode.REVIEW_REQUIRED
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "Human review is required before this can proceed."


class OptimisticLockError(AppError):
    code = ErrorCode.CONFLICT
    http_status = status.HTTP_409_CONFLICT
    default_message = "The resource was modified by another request. Reload and retry."


class AnalysisCooldown(AppError):
    """Deliberate pacing of self-service analysis, not a server-side failure.

    Distinct from a generic rate limit so the client can say *when* the next
    run is available rather than showing a bare "too many requests".
    """

    code = ErrorCode.ANALYSIS_COOLDOWN
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    default_message = "This analysis was run recently."


class UpstreamUnavailable(AppError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "A required downstream service is unavailable."


def drf_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Map every exception to the canonical error envelope."""
    request = context.get("request")
    request_id = getattr(request, "request_id", None) if request is not None else None

    if isinstance(exc, AppError):
        return Response(exc.to_payload(request_id), status=exc.http_status)

    if isinstance(exc, Http404):
        return Response(ResourceNotFound().to_payload(request_id), status=404)

    if isinstance(exc, PermissionDenied):
        return Response(AccessDenied().to_payload(request_id), status=403)

    if isinstance(exc, DjangoValidationError):
        err = ValidationFailed(details={"errors": exc.messages})
        return Response(err.to_payload(request_id), status=err.http_status)

    # Fall back to DRF's handler for its own exceptions, then reshape.
    response = drf_default_handler(exc, context)
    if response is None:
        # Unhandled: DRF's own dispatch() already caught this exception, so
        # by the time Django's request logging sees a 500 response there is
        # no exception left propagating to attach a traceback to - log it
        # here, where it is still live, or every unexpected server error
        # becomes an untraceable generic 500 (spec section 43 hides
        # internals from the *client*; operators still need this).
        import logging

        logging.getLogger("caresense").exception(
            "unhandled_exception", exc_info=exc, extra={"request_id": request_id}
        )
        return Response(
            AppError().to_payload(request_id),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = _code_for_status(response.status_code)
    message = _message_from_drf(response.data)
    response.data = {
        "error": {
            "code": code,
            "message": message,
            "details": _details_from_drf(response.data),
            "request_id": request_id,
        }
    }
    return response


def _code_for_status(http_status: int) -> str:
    return {
        400: ErrorCode.VALIDATION_FAILED,
        401: ErrorCode.AUTHENTICATION_REQUIRED,
        403: ErrorCode.ACCESS_DENIED,
        404: ErrorCode.RESOURCE_NOT_FOUND,
        405: ErrorCode.VALIDATION_FAILED,
        409: ErrorCode.CONFLICT,
        429: ErrorCode.RATE_LIMITED,
    }.get(http_status, ErrorCode.INTERNAL_ERROR)


def _message_from_drf(data: Any) -> str:
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str):
            return detail
    if isinstance(data, list) and data and isinstance(data[0], str):
        return data[0]
    return "The request could not be processed."


def _details_from_drf(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and set(data.keys()) - {"detail"}:
        return {"fields": {k: v for k, v in data.items() if k != "detail"}}
    return {}
