"""Pydantic v2 request/response contracts for the intelligence service.

Payloads are feature dictionaries and identifiers only - never database row
ids the service could use to fetch records (spec section 52).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ``model_version`` / ``model`` are domain terms here, not Pydantic internals.
_ALLOW_MODEL_FIELDS = ConfigDict(protected_namespaces=())


class ReliabilityStatus(str, Enum):
    VALID = "VALID"
    LOW_RELIABILITY = "LOW_RELIABILITY"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class InferenceRequest(BaseModel):
    model_config = _ALLOW_MODEL_FIELDS

    task: str
    model_version: str
    feature_schema_version: str
    features: dict[str, float] = Field(default_factory=dict)
    correlation_id: str


class ReliabilityBlock(BaseModel):
    status: ReliabilityStatus
    detail: dict[str, Any] = Field(default_factory=dict)


class ShapContribution(BaseModel):
    feature: str
    contribution: float


class ModelEcho(BaseModel):
    model_config = _ALLOW_MODEL_FIELDS

    task: str
    model_version: str
    feature_schema_version: str
    artifact_loaded: bool


class InferenceResponse(BaseModel):
    model_config = _ALLOW_MODEL_FIELDS

    raw_score: float | None = None
    calibrated_score: float | None = None
    calibration_version: str = ""
    reliability: ReliabilityBlock
    shap: list[ShapContribution] = Field(default_factory=list)
    model: ModelEcho


class ClassificationRequest(BaseModel):
    text: str
    candidate_labels: list[str] | None = None
    correlation_id: str


class ClassificationResponse(BaseModel):
    label: str
    confidence: float
    status: str
    scores: dict[str, float] = Field(default_factory=dict)
