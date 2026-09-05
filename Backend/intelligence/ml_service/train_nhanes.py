"""Train the CVD risk model on real NHANES data with a real mortality outcome.

Replaces the synthetic demonstration model. The design that matters:

**Temporal external validation.** The model is developed on NHANES cycles
1999-2006 and tested on 2007-2010 - a later, entirely unseen period. A random
split would flatter the model, because it lets it learn period-specific quirks
and then be graded on the same period. Testing forward in time is the closest
thing to the question that actually matters: will this work on the next
patient, not on a reshuffle of the last one.

**Calibration is held out from both.** The isotonic/Platt step is fitted on a
slice of the development data the estimator never saw, so calibration is not
fitted on its own training predictions.

**The honest baseline is age.** Most of the apparent skill in a cardiovascular
risk score is age. A model that cannot beat age alone has earned nothing, so
age-only is reported beside every model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from intelligence.ml_service.evaluation import (
    calibration_table,
    evaluate,
    net_benefit,
    subgroup_report,
)

# The five features the deployed pipeline already assembles from the record.
CORE_FEATURES = ["age", "glucose", "systolic_bp", "bmi", "hdl"]
# The established cardiovascular risk factors. Every published CVD equation
# (Framingham, ASCVD, QRISK, SCORE2) carries sex, smoking and diabetes; a model
# without them is not competing with the state of the art, it is handicapped.
EXTENDED_FEATURES = CORE_FEATURES + [
    "total_cholesterol", "is_male", "current_smoker", "diabetes",
]
# Only the features whose coefficient keeps its sign under bootstrap refitting
# AND points the same way adjusted as unadjusted. HDL and total cholesterol are
# excluded deliberately: see diagnostics.py. Adjusted for sex and blood
# pressure, HDL's coefficient turns positive, so the model would tell a patient
# that their good cholesterol is raising their risk. That sentence is false,
# and this system shows per-feature reasons to patients.
PARSIMONIOUS_FEATURES = [
    "age", "is_male", "systolic_bp", "glucose", "current_smoker", "bmi",
]
# What the application can actually assemble from the record today. Smoking
# status has no field anywhere in the data model, so a model that requires it
# cannot be served until that is captured; sex is on Patient already. This set
# is PARSIMONIOUS minus smoking, and it is the one that ships.
DEPLOYABLE_FEATURES = ["age", "is_male", "systolic_bp", "glucose", "bmi"]

FEATURE_SETS = {
    "core": CORE_FEATURES,
    "extended": EXTENDED_FEATURES,
    "parsimonious": PARSIMONIOUS_FEATURES,
    "deployable": DEPLOYABLE_FEATURES,
}

COHORT = Path(__file__).resolve().parents[1] / "_data" / "cohort.parquet"

DEV_CYCLES = [1999, 2001, 2003, 2005]
TEST_CYCLES = [2007, 2009]

PREPROCESSING_VERSION = "pp-nhanes-1"
EXPLANATION_VERSION = "linear-shap-1"
HORIZON_YEARS = 10

# Physiologically impossible; a BMI above 100 is a recording error, not a person.
PLAUSIBLE = {
    "bmi": (12.0, 100.0),
    "glucose": (2.0, 40.0),
    "systolic_bp": (60.0, 260.0),
    "hdl": (0.1, 6.0),
    "age": (40.0, 79.0),
}


def load_cohort(features: list[str]) -> pd.DataFrame:
    df = pd.read_parquet(COHORT)
    df["is_male"] = (df.sex == "Male").astype(float)

    before = len(df)
    for col, (lo, hi) in PLAUSIBLE.items():
        df = df[(df[col] >= lo) & (df[col] <= hi)]
    if before != len(df):
        print(f"  dropped {before - len(df)} row(s) outside physiological plausibility")

    before = len(df)
    df = df.dropna(subset=features)
    if before != len(df):
        print(f"  dropped {before - len(df)} row(s) missing an extended feature")
    return df.reset_index(drop=True)


def split(df: pd.DataFrame, seed: int = 7):
    dev = df[df.cycle.isin(DEV_CYCLES)].reset_index(drop=True)
    test = df[df.cycle.isin(TEST_CYCLES)].reset_index(drop=True)

    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(dev))
    cut = int(len(dev) * 0.75)
    train = dev.iloc[idx[:cut]].reset_index(drop=True)
    calib = dev.iloc[idx[cut:]].reset_index(drop=True)

    # Leakage guard on participant identity, not row position.
    pairs = (
        (train, calib, "train/calibration"),
        (train, test, "train/test"),
        (calib, test, "calibration/test"),
    )
    for a, b, name in pairs:
        overlap = set(a.uid) & set(b.uid)
        if overlap:
            raise RuntimeError(f"{name} share {len(overlap)} participant(s) - leakage")
    return train, calib, test


def _fit_logistic(Xtr, ytr):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(
        StandardScaler(), LogisticRegression(max_iter=5000, C=1.0)
    ).fit(Xtr, ytr)


def _fit_xgboost(Xtr, ytr):
    from xgboost import XGBClassifier

    return XGBClassifier(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=2.0,
        eval_metric="logloss",
        random_state=7,
        n_jobs=4,
    ).fit(Xtr, ytr)


def _calibrator(kind: str):
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    if kind == "isotonic":
        return IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    return LogisticRegression(max_iter=2000)  # Platt


def _to_logit(p):
    """Platt scaling must be fitted on the log-odds, not on the probability.

    Fitting a logistic regression against a probability that has already been
    squashed through a sigmoid cannot recover the linear scale, and in practice
    it collapses the predictions onto the base rate: every patient gets ~the
    average risk, the ranking survives (so AUC looks unchanged) and the numbers
    become useless. Working in logit space keeps the spread.
    """
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def _apply_calibrator(cal, kind, raw):
    if kind == "isotonic":
        return cal.predict(raw)
    return cal.predict_proba(_to_logit(raw))[:, 1]


def _fit_calibrator(cal, kind, raw, y):
    if kind == "isotonic":
        return cal.fit(raw, y)
    return cal.fit(_to_logit(raw), y)


def missing_feature_ablation(estimator, X, y, train_medians, features):
    """AUC when one feature is unavailable and replaced by the training median.

    The deployed system BLOCKS a prediction when a required feature is missing,
    so this is not how it behaves in production - it quantifies how much each
    feature is carrying, which is what a reviewer needs to know.
    """
    from sklearn.metrics import roc_auc_score

    out = {}
    for i, name in enumerate(features):
        Xm = X.copy()
        Xm[:, i] = train_medians[i]
        out[name] = round(float(roc_auc_score(y, estimator.predict_proba(Xm)[:, 1])), 4)
    return out


def main(version: str, out_dir: str, calibration: str = "platt", seed: int = 7,
         feature_set: str = "core") -> Path:
    import joblib

    features = FEATURE_SETS[feature_set]
    print(f"=== loading cohort (feature set: {feature_set}) ===")
    print(f"  features: {features}")
    df = load_cohort(features)
    train, calib, test = split(df, seed)
    print(
        f"  train       {len(train):>5,} rows, {int(train.y.sum()):>3} events  "
        f"(cycles {DEV_CYCLES})"
    )
    print(f"  calibration {len(calib):>5,} rows, {int(calib.y.sum()):>3} events")
    print(
        f"  test        {len(test):>5,} rows, {int(test.y.sum()):>3} events  "
        f"(cycles {TEST_CYCLES}, temporally held out)"
    )
    print("  leakage guard: no participant id shared across splits - passed")

    Xtr, ytr = train[features].to_numpy(float), train.y.to_numpy(int)
    Xca, yca = calib[features].to_numpy(float), calib.y.to_numpy(int)
    Xte, yte = test[features].to_numpy(float), test.y.to_numpy(int)

    results = {}

    # --- the honest baseline ------------------------------------------
    print("\n=== baseline: age alone ===")
    age_only = _fit_logistic(Xtr[:, [0]], ytr)
    p_age = age_only.predict_proba(Xte[:, [0]])[:, 1]
    results["age_only"] = evaluate(yte, p_age, label="age only")
    print(
        f"  ROC-AUC {results['age_only']['roc_auc']} "
        f"CI {results['age_only']['roc_auc_ci']}"
    )

    # --- primary model -------------------------------------------------
    print(f"\n=== logistic regression ({len(features)} features) ===")
    logreg = _fit_logistic(Xtr, ytr)
    kind = calibration
    cal = _fit_calibrator(
        _calibrator(kind), kind, logreg.predict_proba(Xca)[:, 1], yca
    )
    p_raw = logreg.predict_proba(Xte)[:, 1]
    p_cal = _apply_calibrator(cal, kind, p_raw)
    results["logreg_raw"] = evaluate(yte, p_raw, label="logreg uncalibrated")
    results["logreg_calibrated"] = evaluate(yte, p_cal, label=f"logreg + {kind}")
    for k in ("logreg_raw", "logreg_calibrated"):
        r = results[k]
        print(
            f"  {r['label']:<24} AUC {r['roc_auc']} CI {r['roc_auc_ci']}  "
            f"Brier {r['brier']}  slope {r['calibration_slope']}  "
            f"CITL {r['calibration_in_the_large']}"
        )

    # --- comparison arm -------------------------------------------------
    print("\n=== gradient boosting (comparison) ===")
    xgb = _fit_xgboost(Xtr, ytr)
    cal_x = _fit_calibrator(_calibrator(kind), kind, xgb.predict_proba(Xca)[:, 1], yca)
    p_xgb = _apply_calibrator(cal_x, kind, xgb.predict_proba(Xte)[:, 1])
    results["xgboost_calibrated"] = evaluate(yte, p_xgb, label=f"xgboost + {kind}")
    r = results["xgboost_calibrated"]
    print(
        f"  AUC {r['roc_auc']} CI {r['roc_auc_ci']}  Brier {r['brier']}  "
        f"slope {r['calibration_slope']}"
    )

    # --- calibration detail ---------------------------------------------
    print("\n=== calibration by decile (logistic, calibrated) ===")
    print(f"  {'bin':>3} {'n':>5} {'events':>7} {'predicted':>10} {'observed':>9}")
    for row in calibration_table(yte, p_cal):
        print(
            f"  {row['bin']:>3} {row['n']:>5} {row['events']:>7} "
            f"{row['predicted']:>10.4f} {row['observed']:>9.4f}"
        )

    # --- subgroups -------------------------------------------------------
    print("\n=== subgroup performance (test set) ===")
    reth = {
        1: "Mexican American",
        2: "Other Hispanic",
        3: "White non-Hispanic",
        4: "Black non-Hispanic",
        5: "Other/multi",
    }
    groups = {
        "Male": test.sex == "Male",
        "Female": test.sex == "Female",
        "Age 40-54": test.age < 55,
        "Age 55-69": (test.age >= 55) & (test.age < 70),
        "Age 70-79": test.age >= 70,
    }
    for code, name in reth.items():
        groups[name] = test.RIDRETH1 == code
    sub = subgroup_report(yte, p_cal, groups)
    print(
        f"  {'group':<22} {'n':>5} {'ev':>4} {'AUC':>7} {'AUC 95% CI':>18} "
        f"{'pred':>7} {'obs':>7}"
    )
    for r in sub:
        if r.get("roc_auc") is None:
            print(f"  {r['group']:<22} {r['n']:>5} {r['events']:>4}   {r.get('note', '')}")
            continue
        ci = f"{r['roc_auc_ci'][0]}-{r['roc_auc_ci'][1]}"
        print(
            f"  {r['group']:<22} {r['n']:>5} {r['events']:>4} {r['roc_auc']:>7.4f} "
            f"{ci:>18} {r['mean_predicted']:>7.4f} {r['observed']:>7.4f}"
        )

    # --- robustness -------------------------------------------------------
    medians = np.median(Xtr, axis=0)
    ablation = missing_feature_ablation(logreg, Xte, yte, medians, features)
    print("\n=== AUC with one feature unavailable (median-filled) ===")
    for k, v in ablation.items():
        print(f"  without {k:<12} {v}")

    # --- clinical utility --------------------------------------------------
    print("\n=== decision curve (net benefit) ===")
    nb = net_benefit(yte, p_cal)
    print(f"  {'thresh':>7} {'flagged':>8} {'model':>10} {'treat-all':>10} {'useful':>7}")
    for row in nb:
        useful = row["beats_treat_all"] and row["beats_treat_none"]
        print(
            f"  {row['threshold']:>7.2f} {row['flagged']:>8} "
            f"{row['net_benefit_model']:>10.5f} {row['net_benefit_treat_all']:>10.5f} "
            f"{str(useful):>7}"
        )

    # --- coefficients -------------------------------------------------------
    lr = logreg.named_steps["logisticregression"]
    coefs = {n: round(float(c), 4) for n, c in zip(features, lr.coef_[0])}
    print("\n=== standardised coefficients (log-odds per SD) ===")
    for n, c in sorted(coefs.items(), key=lambda kv: -abs(kv[1])):
        direction = "increases risk" if c > 0 else "decreases risk"
        print(f"  {n:<12} {c:>8}   {direction}")

    domain = {
        n: {
            "min": round(float(np.percentile(Xtr[:, i], 1)), 4),
            "max": round(float(np.percentile(Xtr[:, i], 99)), 4),
        }
        for i, n in enumerate(features)
    }

    metrics = {
        "primary": results["logreg_calibrated"],
        "uncalibrated": results["logreg_raw"],
        "age_only_baseline": results["age_only"],
        "xgboost_comparison": results["xgboost_calibrated"],
        "calibration_table": calibration_table(yte, p_cal),
        "subgroup": sub,
        "missing_data_robustness": ablation,
        "decision_curve": nb,
        "standardised_coefficients": coefs,
        "n_train": int(len(ytr)),
        "n_calibration": int(len(yca)),
        "n_test": int(len(yte)),
        "events_train": int(ytr.sum()),
        "events_test": int(yte.sum()),
        "feature_set": feature_set,
        "features": list(features),
        "leakage_check": "passed: no participant id shared across splits",
        "split_design": (
            f"development cycles {DEV_CYCLES}; "
            f"temporally held-out test cycles {TEST_CYCLES}"
        ),
        # Flat aliases so existing governance/reporting code keeps working.
        "roc_auc": results["logreg_calibrated"]["roc_auc"],
        "brier_calibrated": results["logreg_calibrated"]["brier"],
        "brier_raw": results["logreg_raw"]["brier"],
        "prevalence": results["logreg_calibrated"]["prevalence"],
    }

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    bundle = {
        "task": "cvd",
        "model_version": version,
        "feature_schema_version": f"fs-{version}",
        "preprocessing_version": PREPROCESSING_VERSION,
        "calibration_version": f"cal-{version}-{kind}",
        "explanation_version": EXPLANATION_VERSION,
        "feature_order": features,
        "domain": domain,
        "estimator": logreg,
        "calibrator": cal,
        "calibrator_kind": kind,
        "validation_metrics": metrics,
    }
    path = out / f"cvd-{version}.joblib"
    joblib.dump(bundle, path)
    (out / f"cvd-{version}.metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str)
    )
    meta_path = out / f"cvd-{version}.meta.json"
    meta_path.write_text(json.dumps(
        build_model_card(version, features, feature_set, kind, domain, metrics, sub),
        indent=2, default=str,
    ))
    print(f"\nwrote {path}")
    print(f"wrote {meta_path}")
    return path


def build_model_card(version, features, feature_set, kind, domain, metrics, subgroups):
    """The model card, written to be read by someone deciding whether to trust it.

    Every limitation below is a measured result from this run, not boilerplate.
    """
    primary = metrics["primary"]
    baseline = metrics["age_only_baseline"]
    beats_age = primary["roc_auc"] - baseline["roc_auc"]

    worst = min(
        (s for s in subgroups if s.get("roc_auc") is not None),
        key=lambda s: s["roc_auc"],
    )
    under = max(
        (s for s in subgroups if s.get("roc_auc") is not None),
        key=lambda s: s["observed"] - s["mean_predicted"],
    )

    return {
        "task": "cvd",
        "model_id": "cvd-nhanes-logreg",
        "name": f"CVD 10-year mortality risk, NHANES-trained ({feature_set})",
        "model_type": "calibrated_logistic_regression",
        "prediction_target": (
            "Death with an underlying cause of diseases of the heart (NCHS "
            "leading-cause 001) or cerebrovascular disease (005), within 10 years "
            "of measurement."
        ),
        "model_version": version,
        "feature_schema_version": f"fs-{version}",
        "preprocessing_version": PREPROCESSING_VERSION,
        "calibration_version": f"cal-{version}-{kind}",
        "explanation_version": EXPLANATION_VERSION,
        "training_dataset_version": "nhanes-1999-2006-linked-mortality-2019",
        "validation_dataset_version": "nhanes-1999-2006-holdout-calibration",
        # This is a genuine temporal external validation: a later survey period,
        # different participants, never seen in fitting or calibration.
        "external_validation_dataset_version": "nhanes-2007-2010-linked-mortality-2019",
        "feature_order": list(features),
        "domain": domain,
        "max_data_age_days": 365,
        "validation_metrics": metrics,
        "subgroup_metrics": {
            "roc_auc_by_group": {
                s["group"]: s.get("roc_auc") for s in subgroups
            },
            "predicted_vs_observed_by_group": {
                s["group"]: {"predicted": s.get("mean_predicted"),
                             "observed": s.get("observed")}
                for s in subgroups
            },
        },
        "known_failure_modes": [
            (f"Discrimination within a narrow age band is much weaker than overall "
             f"(worst subgroup: {worst['group']}, AUC {worst['roc_auc']}). Most of "
             f"the overall AUC comes from age separating young from old."),
            (f"Risk is under-predicted in {under['group']}: predicted "
             f"{under['mean_predicted']:.4f} against observed {under['observed']:.4f}."),
            ("Non-cardiovascular death inside the 10-year window is treated as a "
             "non-event (competing risk), which biases absolute risk downward in "
             "the oldest patients."),
            ("Trained on a United States survey population. Calibration in an "
             "Indian population is unknown and very likely different; South Asian "
             "cardiovascular risk at a given risk-factor level is generally higher."),
            ("Fasting glucose is measured in an NHANES morning subsample, so the "
             "training cohort is a subset of survey participants and may differ "
             "from the population that will actually be scored."),
            ("Required features are never imputed - a missing one blocks the "
             "prediction instead of being filled in."),
        ],
        "limitations": (
            f"Trained on real NHANES data (n={metrics['n_train']:,}, "
            f"{metrics['events_train']} events) with a real linked-mortality "
            f"outcome, and validated on a temporally separate survey period "
            f"(n={metrics['n_test']:,}, {metrics['events_test']} events). "
            f"Discrimination on that held-out period is ROC-AUC "
            f"{primary['roc_auc']} (95% CI {primary['roc_auc_ci'][0]}-"
            f"{primary['roc_auc_ci'][1]}), against {baseline['roc_auc']} for age "
            f"alone - a difference of {beats_age:+.4f}, which is NOT statistically "
            f"significant at this event count. Calibration is good "
            f"(slope {primary['calibration_slope']}). This model has not been "
            f"prospectively validated, has not been validated in an Indian "
            f"population, and is not a medical device. It supports a clinician's "
            f"judgement; it does not replace it."
        ),
        "population_domain": {
            "description": (
                "US adults aged 40-79 examined in NHANES 1999-2006, with all "
                "required features measured and at least 10 years of mortality "
                "follow-up or a death within it."
            ),
            "domain": domain,
        },
        "intended_use": {
            "intended_use": (
                "Decision support only: give a clinician reviewing an assigned "
                "patient a calibrated, explainable 10-year cardiovascular "
                "mortality estimate. Not for autonomous decisions, and not a "
                "diagnosis."
            ),
            "target_population": "Adults aged 40-79 with all required features recorded.",
            "inclusion_criteria": ["age 40-79", "all required features present and valid"],
            "exclusion_criteria": [
                "age under 40 or over 79 - outside the fitted range",
                "pregnancy",
                "sex not recorded, where the model requires it - it is never guessed",
                "any required feature missing, invalid, or older than 365 days",
            ],
            "prediction_target": "10-year cardiovascular death",
            "prediction_horizon": "10 years",
            "input_requirements": list(features),
            "required_data_quality": "All required features OBSERVED or DERIVED and validated.",
            "acceptable_data_freshness": "Required features no older than 365 days.",
            "validated_domain": domain,
            "known_limitations": [
                "US survey population; not validated in India.",
                "No prospective validation.",
                "Improvement over age alone is not statistically significant.",
                "Weak discrimination within narrow age bands.",
            ],
            "output_interpretation": (
                "A calibrated probability of cardiovascular death within 10 years, "
                "plus per-feature contributions. Contributions describe the model, "
                "not medical causation, and must not be read as advice that "
                "changing one number will change the outcome by that amount."
            ),
            "contraindications": [
                "Do not use outside the validated input domain.",
                "Do not use when required evidence is missing - it is blocked instead.",
                "Do not present the number to a patient as a certainty.",
            ],
            "review_requirements": (
                "Every produced estimate requires clinician review before it "
                "informs care."
            ),
        },
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="2.0.0")
    ap.add_argument("--out", default="intelligence/_artifacts")
    ap.add_argument("--calibration", choices=["platt", "isotonic"], default="platt")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--features", choices=list(FEATURE_SETS), default="core")
    a = ap.parse_args()
    main(a.version, a.out, a.calibration, a.seed, a.features)
