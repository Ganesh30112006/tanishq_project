"""Reproducible training pipeline for a demo risk model (spec sections 23, 29-31, 34).

This is a *separate, controlled* pipeline. Imputation, resampling and any
synthetic data live here and never touch patient records. It produces:

* ``<task>-<version>.joblib`` - the model bundle the intelligence service loads
* ``<task>-<version>.meta.json`` - metadata for ``manage.py register_model``

The demo model is a calibrated logistic regression on synthetic, independent
rows (no repeated "patients", so there is no patient-level leakage between the
train / calibration / test splits). Given a fixed seed it is deterministic.

Usage::

    python -m intelligence.ml_service.train --task cvd --version 1.0.0 \
        --out intelligence/_artifacts
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FEATURE_ORDER = ["age", "glucose", "systolic_bp", "bmi", "hdl"]
# True generative coefficients (logit space) for the synthetic outcome.
_TRUE_COEF = {"age": 0.04, "glucose": 0.55, "systolic_bp": 0.03, "bmi": 0.06, "hdl": -0.9}
_TRUE_BIAS = -8.5

PREPROCESSING_VERSION = "pp-1"
EXPLANATION_VERSION = "linear-shap-1"


def _synthetic(n: int, seed: int):
    import numpy as np

    rng = np.random.default_rng(seed)
    age = rng.normal(55, 12, n).clip(18, 95)
    glucose = rng.normal(5.6, 1.4, n).clip(3.0, 20.0)          # mmol/L
    systolic = rng.normal(128, 16, n).clip(85, 210)
    bmi = rng.normal(27, 4.5, n).clip(15, 55)
    hdl = rng.normal(1.3, 0.35, n).clip(0.4, 3.2)              # mmol/L
    X = np.column_stack([age, glucose, systolic, bmi, hdl])

    logit = (
        _TRUE_BIAS
        + _TRUE_COEF["age"] * age
        + _TRUE_COEF["glucose"] * glucose
        + _TRUE_COEF["systolic_bp"] * systolic
        + _TRUE_COEF["bmi"] * bmi
        + _TRUE_COEF["hdl"] * hdl
    )
    p = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.random(n) < p).astype(int)

    # Non-predictive attributes used only for subgroup / temporal validation.
    subgroup = rng.integers(0, 2, n)                 # e.g. a demographic stratum
    period = rng.integers(0, 3, n)                   # enrolment period 0..2
    row_id = seed * 1_000_000 + np.arange(n)         # unique row identity
    return X, y, {"subgroup": subgroup, "period": period, "row_id": row_id}


def _missing_data_auc(estimator, X_test, y_test, roc_auc_score) -> dict:
    """AUC when one feature at a time is set to the training median (a crude
    proxy for that feature being unavailable at inference)."""
    import numpy as np

    out: dict[str, float] = {}
    medians = np.median(X_test, axis=0)
    for i, name in enumerate(FEATURE_ORDER):
        Xm = X_test.copy()
        Xm[:, i] = medians[i]
        proba = estimator.predict_proba(Xm)[:, 1]
        out[name] = round(float(roc_auc_score(y_test, proba)), 4)
    return out


def build_demo_model(task: str, version: str, out_dir: str | Path, *, seed: int = 7) -> Path:
    import joblib
    import numpy as np
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    X_train, y_train, meta_train = _synthetic(6000, seed)
    X_calib, y_calib, _ = _synthetic(2000, seed + 1)
    X_test, y_test, meta_test = _synthetic(2000, seed + 2)

    # Leakage guard: train / calibration / test rows must not overlap. The
    # synthetic generator gives every row a unique id per split, so this is an
    # explicit assertion rather than a train/test contamination risk.
    train_ids = set(meta_train["row_id"].tolist())
    test_ids = set(meta_test["row_id"].tolist())
    if train_ids & test_ids:
        raise RuntimeError("Row-identity overlap between train and test splits (leakage).")

    estimator = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    estimator.fit(X_train, y_train)

    raw_calib = estimator.predict_proba(X_calib)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(raw_calib, y_calib)

    raw_test = estimator.predict_proba(X_test)[:, 1]
    cal_test = calibrator.predict(raw_test)

    def _auc(mask) -> float | None:
        yy = y_test[mask]
        if yy.min() == yy.max():
            return None
        return round(float(roc_auc_score(yy, raw_test[mask])), 4)

    subgroup_auc = {
        f"subgroup_{g}": _auc(meta_test["subgroup"] == g) for g in (0, 1)
    }
    temporal_auc = {
        f"period_{p}": _auc(meta_test["period"] == p) for p in (0, 1, 2)
    }

    metrics = {
        "roc_auc": round(float(roc_auc_score(y_test, raw_test)), 4),
        "brier_raw": round(float(brier_score_loss(y_test, raw_test)), 4),
        "brier_calibrated": round(float(brier_score_loss(y_test, cal_test)), 4),
        "prevalence": round(float(np.mean(y_test)), 4),
        "n_train": int(len(y_train)),
        "n_calibration": int(len(y_calib)),
        "n_test": int(len(y_test)),
        "leakage_check": "passed",
        "subgroup_roc_auc": subgroup_auc,
        "temporal_roc_auc": temporal_auc,
        "missing_data_robustness": _missing_data_auc(estimator, X_test, y_test, roc_auc_score),
    }

    # Validated input domain: 1st-99th percentile of the training data.
    domain = {
        name: {
            "min": round(float(np.percentile(X_train[:, i], 1)), 4),
            "max": round(float(np.percentile(X_train[:, i], 99)), 4),
        }
        for i, name in enumerate(FEATURE_ORDER)
    }

    feature_schema_version = f"fs-{version}"
    calibration_version = f"cal-{version}"
    bundle = {
        "task": task,
        "model_version": version,
        "feature_schema_version": feature_schema_version,
        "preprocessing_version": PREPROCESSING_VERSION,
        "calibration_version": calibration_version,
        "explanation_version": EXPLANATION_VERSION,
        "feature_order": FEATURE_ORDER,
        "domain": domain,
        "estimator": estimator,
        "calibrator": calibrator,
        "validation_metrics": metrics,
    }
    bundle_path = out_dir / f"{task}-{version}.joblib"
    joblib.dump(bundle, bundle_path)

    meta = {
        "task": task,
        "model_id": f"{task}-logreg",
        "name": f"{task.upper()} calibrated logistic regression (demo)",
        "model_type": "calibrated_logistic_regression",
        "prediction_target": f"{task} outcome within the prediction horizon (synthetic)",
        "model_version": version,
        "feature_schema_version": feature_schema_version,
        "preprocessing_version": PREPROCESSING_VERSION,
        "calibration_version": calibration_version,
        "explanation_version": EXPLANATION_VERSION,
        "training_dataset_version": f"synthetic-{version}",
        "validation_dataset_version": f"synthetic-holdout-{version}",
        "external_validation_dataset_version": "",
        "feature_order": FEATURE_ORDER,
        "domain": domain,
        "max_data_age_days": 365,
        "validation_metrics": metrics,
        # Surfaced as ModelVersion.subgroup_metrics for governance review (§55).
        "subgroup_metrics": {
            "roc_auc_by_subgroup": subgroup_auc,
            "roc_auc_by_period": temporal_auc,
        },
        "known_failure_modes": [
            "Synthetic training distribution; real-world calibration is unknown.",
            "Feature median imputation is not used - a missing required feature blocks the prediction.",
        ],
        "limitations": (
            "Trained on synthetic data for demonstration. Not clinically validated. "
            "No external validation performed."
        ),
        "population_domain": {"description": "synthetic adults 18-95", "domain": domain},
        # Structured intended-use definition (spec section 4). This is a
        # demonstration template - a real model needs a clinically authored one.
        "intended_use": {
            "intended_use": (
                "Decision support only: provide a calibrated, explainable risk "
                "estimate to a clinician reviewing an assigned patient. Not for "
                "autonomous decisions."
            ),
            "target_population": "Adults aged 18-95 with the required features recorded.",
            "inclusion_criteria": ["age 18-95", "all required features present and valid"],
            "exclusion_criteria": ["age <18", "pregnancy", "required feature missing or stale"],
            "prediction_target": f"{task} outcome (synthetic demonstration target)",
            "prediction_horizon": "unspecified (demonstration model)",
            "input_requirements": FEATURE_ORDER,
            "required_data_quality": "All required features OBSERVED or DERIVED and validated.",
            "acceptable_data_freshness": "Required features no older than 365 days.",
            "validated_domain": domain,
            "known_limitations": [
                "Synthetic data only.",
                "No external or prospective validation.",
                "Subgroup performance computed on synthetic strata only.",
            ],
            "output_interpretation": (
                "A calibrated probability plus SHAP contributions. Contributions "
                "describe the model, not medical causation."
            ),
            "contraindications": [
                "Do not use outside the validated input domain.",
                "Do not use when required evidence is missing - the prediction is blocked instead.",
            ],
            "review_requirements": (
                "Every produced estimate requires clinician review before it informs care."
            ),
        },
    }
    (out_dir / f"{task}-{version}.meta.json").write_text(json.dumps(meta, indent=2))
    return bundle_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="cvd")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--out", default="intelligence/_artifacts")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    path = build_demo_model(args.task, args.version, args.out, seed=args.seed)
    print(f"wrote {path}")
    print(f"wrote {path.parent / f'{args.task}-{args.version}.meta.json'}")


if __name__ == "__main__":
    main()
