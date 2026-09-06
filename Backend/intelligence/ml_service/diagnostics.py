"""Diagnostics that decide whether a model is safe to show a patient.

Two questions the headline metrics cannot answer:

1. **Is the improvement real, or noise?** Comparing two AUCs computed on the
   same test set by eye is meaningless. The paired bootstrap resamples the
   same patients for both models, so the difference keeps its correlation.

2. **Does each coefficient point the way the biology does?** This system shows
   per-feature contributions to patients. A coefficient with the wrong sign
   produces a sentence like "your good cholesterol is raising your risk",
   which is both false and actionable in the wrong direction. Sign
   instability across specifications is the warning sign, so it is measured
   rather than assumed.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from intelligence.ml_service.train_nhanes import (
    COHORTS,
    FEATURE_SETS,
    load_cohort,
    resolve_features,
    split,
)


def paired_bootstrap_auc_diff(y, p_a, p_b, n_boot=4000, seed=13):
    """95% CI for AUC(b) - AUC(a) on the same patients."""
    rng = np.random.default_rng(seed)
    y, p_a, p_b = np.asarray(y), np.asarray(p_a), np.asarray(p_b)
    diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(y), len(y))
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        diffs.append(roc_auc_score(yy, p_b[idx]) - roc_auc_score(yy, p_a[idx]))
    diffs = np.array(diffs)
    return {
        "mean_diff": round(float(diffs.mean()), 4),
        "ci": (round(float(np.percentile(diffs, 2.5)), 4),
               round(float(np.percentile(diffs, 97.5)), 4)),
        "p_b_better": round(float((diffs > 0).mean()), 4),
    }


def _fit(X, y):
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000)).fit(X, y)


def coefficient_stability(train, features, n_boot=500, seed=17):
    """How often does each coefficient keep its sign across bootstrap refits?

    A feature whose sign flips in a meaningful share of resamples is not
    supporting a causal story; showing it to a patient as a reason is a
    misrepresentation of what the model knows.
    """
    rng = np.random.default_rng(seed)
    X = train[features].to_numpy(float)
    y = train.y.to_numpy(int)
    coefs = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(y), len(y))
        if y[idx].min() == y[idx].max():
            continue
        m = _fit(X[idx], y[idx])
        coefs.append(m.named_steps["logisticregression"].coef_[0])
    C = np.vstack(coefs)
    point = _fit(X, y).named_steps["logisticregression"].coef_[0]
    rows = []
    for i, name in enumerate(features):
        col = C[:, i]
        share_pos = float((col > 0).mean())
        rows.append({
            "feature": name,
            "coef": round(float(point[i]), 4),
            "ci": (round(float(np.percentile(col, 2.5)), 4),
                   round(float(np.percentile(col, 97.5)), 4)),
            "sign_stability": round(max(share_pos, 1 - share_pos), 3),
            "crosses_zero": bool(np.percentile(col, 2.5) < 0 < np.percentile(col, 97.5)),
        })
    return rows


def univariate_direction(df, features):
    """The unadjusted association of each feature with the outcome.

    If a feature is protective on its own but harmful once other features are
    present, the multivariable coefficient is describing a residual after
    adjustment, not the effect a patient would experience by changing it.
    """
    rows = []
    for f in features:
        X = df[[f]].to_numpy(float)
        y = df.y.to_numpy(int)
        m = _fit(X, y)
        c = float(m.named_steps["logisticregression"].coef_[0][0])
        hi = df[df[f] > df[f].median()].y.mean()
        lo = df[df[f] <= df[f].median()].y.mean()
        rows.append({
            "feature": f,
            "univariate_coef": round(c, 4),
            "event_rate_above_median": round(float(hi), 4),
            "event_rate_below_median": round(float(lo), 4),
        })
    return rows


def _clears(rates, se, high, low, sensitivity):
    """Is bin ``high`` above bin ``low`` by more than the noise in both?"""
    return rates[high] - rates[low] > sensitivity * np.hypot(se[high], se[low])


def monotonicity_check(train, features, coefs, bins=5, sensitivity=1.0):
    """Does the observed event rate actually move the way the coefficient claims?

    Sign stability cannot answer this, and that is a real blind spot. A U-shaped
    relationship produces a perfectly stable coefficient with a perfectly
    consistent sign, and still tells the patients at one end of the range the
    exact opposite of the truth.

    BMI is the worked example. Ten-year cardiovascular death is U-shaped in BMI:
    highest in the leanest group, lowest in the middle, high again at the top,
    because low weight in older adults is often illness and frailty rather than
    health. A linear coefficient is positive and stable, so it passes every
    other test here, and it tells a frail underweight patient that their weight
    is REDUCING their risk - which is backwards, and this system shows
    per-feature reasons to patients.

    The trough must sit above one standard error from both ends to be reported.
    That is deliberately sensitive rather than a 95% test: this is a screen, and
    missing a reason that points a patient the wrong way is far worse than
    looking into a false alarm.
    """
    rows = []
    for name in features:
        x = train[name].to_numpy(float)
        y = train["y"].to_numpy(int)
        coef = coefs.get(name, 0.0)

        if len(np.unique(x)) <= 2:
            rows.append({"feature": name, "shape": "binary", "monotone": True,
                         "rates": [], "note": "two-valued; monotone by definition"})
            continue

        edges = np.unique(np.quantile(x, np.linspace(0, 1, bins + 1)))
        idx = np.clip(np.digitize(x, edges[1:-1]), 0, len(edges) - 2)
        rates, ns = [], []
        for b in range(len(edges) - 1):
            m = idx == b
            ns.append(int(m.sum()))
            rates.append(float(y[m].mean()) if m.any() else float("nan"))
        rates_a, ns_a = np.array(rates), np.array(ns)
        se = np.sqrt(np.clip(rates_a * (1 - rates_a), 0, None) / np.maximum(ns_a, 1))

        # An interior extremum that both ends clear by more than a standard
        # error is a bend, not noise.
        interior = np.arange(1, len(rates_a) - 1)
        shape, monotone = "monotone", True
        if len(interior):
            lo = interior[int(np.argmin(rates_a[interior]))]
            hi = interior[int(np.argmax(rates_a[interior]))]
            if _clears(rates_a, se, 0, lo, sensitivity) and _clears(
                rates_a, se, len(rates_a) - 1, lo, sensitivity
            ):
                shape, monotone = "U-shaped (lowest risk in the middle)", False
            elif _clears(rates_a, se, hi, 0, sensitivity) and _clears(
                rates_a, se, hi, len(rates_a) - 1, sensitivity
            ):
                shape, monotone = "inverted-U (highest risk in the middle)", False

        # Direction: does the fitted sign match the observed end-to-end trend?
        trend = rates_a[-1] - rates_a[0]
        direction_agrees = (trend > 0) == (coef > 0) if coef != 0 else True

        # The question that decides whether this feature may be shown to a
        # patient as a reason is narrower than "is there a bend". Blood pressure
        # bends too - the very lowest readings carry slightly more risk than the
        # next band up - and telling someone with a low reading that it helps
        # them is both true and harmless, because low readings really are the
        # low-risk end.
        #
        # The harm is specific: the model points at one end of the range and
        # calls it protective when that end is actually among the WORST. That is
        # what BMI does. So the test is - take the end the coefficient treats as
        # most protective, and ask whether it is genuinely low risk. It fails if
        # that end sits above the middle of the observed rates by more than the
        # noise in it.
        protective = 0 if coef > 0 else len(rates_a) - 1
        typical = float(np.median(rates_a))
        misleads = bool(
            rates_a[protective] > typical
            and rates_a[protective] - float(np.min(rates_a))
            > sensitivity * se[protective]
        )

        rows.append({
            "feature": name, "coef": round(float(coef), 4), "shape": shape,
            "monotone": monotone, "direction_agrees": bool(direction_agrees),
            "misleads_protected_end": misleads,
            "protective_end_rate": round(float(rates_a[protective]), 4),
            "lowest_observed_rate": round(float(np.min(rates_a)), 4),
            "rates": [round(float(r), 4) for r in rates_a], "n": ns,
        })
    return rows


def main(cohort: str = "fasting", feature_set: str = "extended",
         baseline_set: str = "core") -> None:
    """Run the safety diagnostics against a specific cohort and feature set.

    This used to be hard-wired to the fasting cohort and the extended feature
    set, which meant the sign-stability rule - the one that decides whether a
    coefficient may be shown to a patient as a reason - was never actually run
    against whichever model was shipping.
    """
    _file, marker = COHORTS[cohort]
    features = resolve_features(FEATURE_SETS[feature_set], marker)
    baseline = resolve_features(FEATURE_SETS[baseline_set], marker)
    needed = sorted(set(features) | set(baseline) | {"age"})

    print(f"cohort={cohort}  features={feature_set}  baseline={baseline_set}")
    df = load_cohort(needed, cohort)
    tr, _ca, te = split(df)
    y = te.y.to_numpy(int)
    ytr = tr.y.to_numpy(int)

    print(f"\n=== 1. does {feature_set} beat age alone, and {baseline_set}? ===")
    column_sets = {"age": ["age"], baseline_set: baseline, feature_set: features}
    preds = {}
    for name, cols in column_sets.items():
        model = _fit(tr[cols].to_numpy(float), ytr)
        preds[name] = model.predict_proba(te[cols].to_numpy(float))[:, 1]
        print(f"  {name:<16} AUC {roc_auc_score(y, preds[name]):.4f}")

    print()
    comparisons = [
        (f"{baseline_set} vs age-only", preds["age"], preds[baseline_set]),
        (f"{feature_set} vs age-only", preds["age"], preds[feature_set]),
        (f"{feature_set} vs {baseline_set}", preds[baseline_set], preds[feature_set]),
    ]
    for label, a, b in comparisons:
        r = paired_bootstrap_auc_diff(y, a, b)
        verdict = "REAL" if r["ci"][0] > 0 else "not distinguishable from noise"
        print(f"  {label:<34} dAUC {r['mean_diff']:+.4f}  "
              f"CI {r['ci']}  P(better)={r['p_b_better']}  -> {verdict}")

    print(f"\n=== 2. coefficient sign stability ({feature_set}, 500 refits) ===")
    print(f"  {'feature':<20} {'coef':>8} {'95% CI':>22} "
          f"{'sign stab':>10} {'crosses 0':>10}")
    unstable = []
    for r in coefficient_stability(tr, features):
        flag = ""
        if r["crosses_zero"]:
            flag = "  <-- unstable"
            unstable.append(r["feature"])
        print(f"  {r['feature']:<20} {r['coef']:>8.4f} "
              f"{str(r['ci']):>22} {r['sign_stability']:>10.3f} "
              f"{str(r['crosses_zero']):>10}{flag}")

    print("\n=== 3. unadjusted direction vs adjusted direction ===")
    print("  A sign that flips between these two columns means the adjusted")
    print("  coefficient must NOT be shown to a patient as a reason.\n")
    uni = {r["feature"]: r for r in univariate_direction(tr, features)}
    adj = {r["feature"]: r for r in coefficient_stability(tr, features, n_boot=200)}
    print(f"  {'feature':<20} {'unadjusted':>11} {'adjusted':>10} {'agree?':>8} "
          f"{'ev>med':>8} {'ev<=med':>8}")
    flipped = []
    for f in features:
        u, a = uni[f]["univariate_coef"], adj[f]["coef"]
        agree = (u > 0) == (a > 0)
        if not agree:
            flipped.append(f)
        print(f"  {f:<20} {u:>11.4f} {a:>10.4f} {('yes' if agree else 'NO'):>8} "
              f"{uni[f]['event_rate_above_median']:>8.4f} "
              f"{uni[f]['event_rate_below_median']:>8.4f}")

    print("\n=== 4. shape: does observed risk move the way the coefficient says? ===")
    print("  Sign stability cannot see a bend. A U-shaped relationship has a")
    print("  perfectly stable coefficient and still points one end of the range")
    print("  the wrong way.\n")
    fitted = _fit(tr[features].to_numpy(float), ytr)
    coefs = dict(zip(features,
                     fitted.named_steps["logisticregression"].coef_[0], strict=True))
    bent = []
    print(f"  {'feature':<20} {'coef':>8}  {'event rate by quintile':<44} shape")
    for r in monotonicity_check(tr, features, coefs):
        rates = " ".join(f"{v:.4f}" for v in r["rates"]) or "-"
        if r.get("misleads_protected_end") or not r.get("direction_agrees", True):
            bent.append(r["feature"])
            note = (f"{r['shape']}  <-- calls its safest end "
                    f"{r['protective_end_rate']} when the safest is "
                    f"{r['lowest_observed_rate']}")
        else:
            note = r["shape"]
        print(f"  {r['feature']:<20} {r.get('coef', 0):>8}  {rates:<44} {note}")

    print("\n=== verdict ===")
    unsafe = sorted(set(unstable) | set(flipped) | set(bent))
    if unsafe:
        print("  NOT SAFE to show per-feature reasons for: " + ", ".join(unsafe))
        print("  A coefficient whose sign is unstable, flips under adjustment, or")
        print("  describes a straight line through a bent relationship produces a")
        print("  patient-facing sentence that points the wrong way.")
    else:
        print("  All coefficients keep their sign under bootstrap refitting and")
        print("  point the same way adjusted as unadjusted. Every feature in")
        print("  this set is safe to show a patient as a reason.")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", choices=list(COHORTS), default="fasting")
    ap.add_argument("--features", choices=list(FEATURE_SETS), default="extended")
    ap.add_argument("--baseline", choices=list(FEATURE_SETS), default="core")
    a = ap.parse_args()
    main(a.cohort, a.features, a.baseline)
