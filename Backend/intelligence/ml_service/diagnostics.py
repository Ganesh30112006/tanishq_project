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
    CORE_FEATURES,
    EXTENDED_FEATURES,
    load_cohort,
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


def main() -> None:
    print("=== 1. does the extended model really beat age alone, and the core set? ===")
    df_ext = load_cohort(EXTENDED_FEATURES)
    tr, ca, te = split(df_ext)

    y = te.y.to_numpy(int)
    m_age = _fit(tr[["age"]].to_numpy(float), tr.y.to_numpy(int))
    m_core = _fit(tr[CORE_FEATURES].to_numpy(float), tr.y.to_numpy(int))
    m_ext = _fit(tr[EXTENDED_FEATURES].to_numpy(float), tr.y.to_numpy(int))

    p_age = m_age.predict_proba(te[["age"]].to_numpy(float))[:, 1]
    p_core = m_core.predict_proba(te[CORE_FEATURES].to_numpy(float))[:, 1]
    p_ext = m_ext.predict_proba(te[EXTENDED_FEATURES].to_numpy(float))[:, 1]

    for label, a, b in (
        ("core (5 feat) vs age-only", p_age, p_core),
        ("extended (9 feat) vs age-only", p_age, p_ext),
        ("extended vs core", p_core, p_ext),
    ):
        r = paired_bootstrap_auc_diff(y, a, b)
        verdict = "REAL" if r["ci"][0] > 0 else "not distinguishable from noise"
        print(f"  {label:<32} dAUC {r['mean_diff']:+.4f}  "
              f"CI {r['ci']}  P(better)={r['p_b_better']}  -> {verdict}")

    print("\n=== 2. coefficient sign stability (extended, 500 bootstrap refits) ===")
    print(f"  {'feature':<20} {'coef':>8} {'95% CI':>22} {'sign stab':>10} {'crosses 0':>10}")
    for r in coefficient_stability(tr, EXTENDED_FEATURES):
        flag = "  <-- unstable" if r["crosses_zero"] else ""
        print(f"  {r['feature']:<20} {r['coef']:>8.4f} "
              f"{str(r['ci']):>22} {r['sign_stability']:>10.3f} "
              f"{str(r['crosses_zero']):>10}{flag}")

    print("\n=== 3. unadjusted direction vs adjusted direction ===")
    print("  A sign that flips between these two columns means the adjusted")
    print("  coefficient must NOT be shown to a patient as a reason.\n")
    uni = {r["feature"]: r for r in univariate_direction(tr, EXTENDED_FEATURES)}
    adj = {r["feature"]: r for r in coefficient_stability(tr, EXTENDED_FEATURES, n_boot=200)}
    print(f"  {'feature':<20} {'unadjusted':>11} {'adjusted':>10} {'agree?':>8} "
          f"{'ev>med':>8} {'ev<=med':>8}")
    for f in EXTENDED_FEATURES:
        u, a = uni[f]["univariate_coef"], adj[f]["coef"]
        agree = "yes" if (u > 0) == (a > 0) else "NO"
        print(f"  {f:<20} {u:>11.4f} {a:>10.4f} {agree:>8} "
              f"{uni[f]['event_rate_above_median']:>8.4f} "
              f"{uni[f]['event_rate_below_median']:>8.4f}")


if __name__ == "__main__":
    main()
