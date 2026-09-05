"""Inference endpoint (spec sections 28-32, 35).

Pipeline when an artifact is available::

    raw model output -> calibration -> calibrated risk -> reliability/OOD check
    -> SHAP contributions

When no artifact is registered for ``(task, model_version)`` the response is
an explicit ``REVIEW_REQUIRED`` reliability verdict with null scores. Django
then records a BLOCKED assessment - uncertainty is never converted into a
confident result.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from intelligence.anomaly.ood import reliability_for
from intelligence.explainability.shap_runner import top_contributions
from intelligence.ml_service.registry import LoadedModel, load
from intelligence.schemas import (
    InferenceRequest,
    InferenceResponse,
    ModelEcho,
    ReliabilityBlock,
    ReliabilityStatus,
)
from intelligence.security import verify_service_request

router = APIRouter(tags=["ml"])


@router.post("/infer", response_model=InferenceResponse)
async def infer(
    payload: InferenceRequest,
    _correlation_id: str = Depends(verify_service_request),
) -> InferenceResponse:
    model = load(payload.task, payload.model_version)
    echo = ModelEcho(
        task=payload.task,
        model_version=payload.model_version,
        feature_schema_version=payload.feature_schema_version,
        artifact_loaded=model is not None,
    )

    if model is None:
        return InferenceResponse(
            reliability=ReliabilityBlock(
                status=ReliabilityStatus.REVIEW_REQUIRED,
                detail={"reason": "No registered model artifact for this task/version."},
            ),
            model=echo,
        )

    if payload.feature_schema_version and payload.feature_schema_version != model.feature_schema_version:
        return InferenceResponse(
            reliability=ReliabilityBlock(
                status=ReliabilityStatus.REVIEW_REQUIRED,
                detail={
                    "reason": "Feature schema version mismatch.",
                    "expected": model.feature_schema_version,
                    "received": payload.feature_schema_version,
                },
            ),
            model=echo,
        )

    reliability = reliability_for(model, payload.features)
    if reliability.status in {
        ReliabilityStatus.INSUFFICIENT_DATA,
        ReliabilityStatus.OUT_OF_DOMAIN,
    }:
        # Still return the verdict (with no score) so Django can block/qualify.
        return InferenceResponse(reliability=reliability, model=echo)

    raw = _predict_proba(model, payload.features)
    calibrated = _calibrate(model, raw)
    shap = top_contributions(model, payload.features)
    return InferenceResponse(
        raw_score=raw,
        calibrated_score=calibrated,
        calibration_version=model.calibration_version,
        reliability=reliability,
        shap=shap,
        model=echo,
    )


def _vector(model: LoadedModel, features: dict[str, float]) -> list[float]:
    return [float(features[name]) for name in model.feature_order]


def _predict_proba(model: LoadedModel, features: dict[str, float]) -> float:
    proba = model.estimator.predict_proba([_vector(model, features)])[0]
    # Positive class is index 1 for a binary classifier.
    return float(proba[1] if len(proba) > 1 else proba[0])


def _calibrate(model: LoadedModel, raw: float) -> float:
    """Apply the fitted calibrator, whichever of the two kinds it is.

    Isotonic regression maps a probability straight to a probability. Platt
    scaling is a logistic regression fitted on the *log-odds*, so the raw
    probability has to be taken back to logit space first and read out of
    ``predict_proba`` - calling ``predict`` on it would return a 0/1 class
    label, which would silently turn every risk estimate into 0% or 100%.
    """
    if model.calibrator is None:
        return raw
    if model.calibrator_kind == "platt":
        import math

        p = min(1 - 1e-6, max(1e-6, raw))
        logit = math.log(p / (1 - p))
        calibrated = float(model.calibrator.predict_proba([[logit]])[0][1])
    else:
        calibrated = float(model.calibrator.predict([raw])[0])
    return min(1.0, max(0.0, calibrated))
