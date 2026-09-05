"""SHAP-style explanations (spec section 35).

SHAP explains *model behaviour* - how much each feature moved this
prediction. It does NOT prove biological causation; callers must not phrase a
contribution as a confirmed medical cause.

If the ``shap`` package is installed it is used. Otherwise, for a linear model
(``StandardScaler`` + ``LogisticRegression`` pipeline) we compute the exact
additive attribution in logit space, which equals the SHAP value for a linear
model with independent features:

    contribution_i = coef_i * (x_i - mean_i) / scale_i
"""
from __future__ import annotations

from intelligence.ml_service.registry import LoadedModel
from intelligence.schemas import ShapContribution


def top_contributions(
    model: LoadedModel, features: dict[str, float], *, limit: int = 10
) -> list[ShapContribution]:
    vector = [float(features[name]) for name in model.feature_order]
    try:
        contribs = _linear_attribution(model, vector)
    except (AttributeError, TypeError, ValueError):
        contribs = _shap_attribution(model, vector)

    paired = list(zip(model.feature_order, contribs, strict=True))
    paired.sort(key=lambda kv: abs(kv[1]), reverse=True)
    return [ShapContribution(feature=name, contribution=round(value, 6)) for name, value in paired[:limit]]


def _linear_attribution(model: LoadedModel, vector: list[float]) -> list[float]:
    estimator = model.estimator
    # Pipeline: named steps or ordered steps.
    steps = getattr(estimator, "named_steps", None) or dict(getattr(estimator, "steps", []))
    scaler = steps.get("standardscaler") or steps.get("scaler")
    clf = steps.get("logisticregression") or steps.get("clf") or steps.get("model")
    if clf is None:
        raise AttributeError("no linear classifier in pipeline")

    coef = list(clf.coef_[0])
    if scaler is not None:
        mean = list(scaler.mean_)
        scale = list(scaler.scale_)
        return [c * (x - m) / s for c, x, m, s in zip(coef, vector, mean, scale, strict=True)]
    return [c * x for c, x in zip(coef, vector, strict=True)]


def _shap_attribution(model: LoadedModel, vector: list[float]) -> list[float]:  # pragma: no cover
    import numpy as np
    import shap

    explainer = shap.Explainer(model.estimator.predict, np.array([vector]))
    values = explainer(np.array([vector])).values[0]
    return [float(v) for v in values]
