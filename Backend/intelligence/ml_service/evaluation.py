"""Evaluation battery for a clinical risk model.

Discrimination alone is close to meaningless for a risk score that will be
shown to a person. A model can rank patients well (high AUC) and still tell
every one of them a number that is wrong by a factor of three. So this module
reports discrimination, calibration, subgroup behaviour and clinical utility
together, and every headline number carries a bootstrap confidence interval -
with 331 events, the third decimal place is noise and the interval says so.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

EPS = 1e-9


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def bootstrap_ci(y, p, fn, n_boot: int = 2000, seed: int = 11):
    """Percentile bootstrap. Resamples that lose a class are skipped."""
    rng = np.random.default_rng(seed)
    y, p = np.asarray(y), np.asarray(p)
    stats = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(y), len(y))
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        stats.append(fn(yy, p[idx]))
    if not stats:
        return (None, None)
    return (round(float(np.percentile(stats, 2.5)), 4),
            round(float(np.percentile(stats, 97.5)), 4))


def calibration_slope_intercept(y, p):
    """Regress the outcome on the predicted logit.

    Slope 1 / intercept 0 is perfect. Slope < 1 means predictions are too
    extreme; a negative intercept means the model over-predicts overall.
    """
    from sklearn.linear_model import LogisticRegression

    lp = _logit(np.asarray(p)).reshape(-1, 1)
    y = np.asarray(y)
    if y.min() == y.max():
        return None, None
    slope = LogisticRegression(penalty=None, max_iter=2000).fit(lp, y)
    intercept_only = LogisticRegression(penalty=None, max_iter=2000, fit_intercept=True)
    # calibration-in-the-large: offset the logit, fit intercept only
    intercept_only.fit(np.zeros_like(lp), y)
    mean_pred_logit = float(np.mean(lp))
    cil = float(intercept_only.intercept_[0]) - mean_pred_logit
    return round(float(slope.coef_[0][0]), 4), round(cil, 4)


def calibration_table(y, p, bins: int = 10):
    """Observed vs predicted risk by predicted-risk decile."""
    y, p = np.asarray(y), np.asarray(p)
    qs = np.quantile(p, np.linspace(0, 1, bins + 1))
    qs[0], qs[-1] = -np.inf, np.inf
    rows = []
    for i in range(bins):
        m = (p > qs[i]) & (p <= qs[i + 1])
        if m.sum() == 0:
            continue
        rows.append({
            "bin": i + 1,
            "n": int(m.sum()),
            "predicted": round(float(p[m].mean()), 4),
            "observed": round(float(y[m].mean()), 4),
            "events": int(y[m].sum()),
        })
    return rows


def hosmer_lemeshow(y, p, bins: int = 10):
    """Chi-square goodness of fit across deciles of predicted risk.

    A large statistic (small p-value) means predicted and observed disagree.
    With big samples this rejects on trivial miscalibration, so read it
    alongside the calibration table, not instead of it.
    """
    from scipy.stats import chi2

    rows = calibration_table(y, p, bins)
    stat = 0.0
    for r in rows:
        n, obs = r["n"], r["events"]
        exp = r["predicted"] * n
        if exp <= 0 or exp >= n:
            continue
        stat += (obs - exp) ** 2 / (exp * (1 - r["predicted"]))
    dof = max(len(rows) - 2, 1)
    return round(float(stat), 3), round(float(1 - chi2.cdf(stat, dof)), 4)


def net_benefit(y, p, thresholds=None):
    """Decision-curve analysis.

    Net benefit at threshold t answers: if we acted on everyone predicted
    above t, how many true positives do we gain net of the false positives,
    weighted by the odds a clinician implicitly accepts by choosing t? A model
    is only useful where it beats both 'treat all' and 'treat none'.
    """
    y, p = np.asarray(y), np.asarray(p)
    n = len(y)
    thresholds = thresholds if thresholds is not None else [.01, .02, .05, .10, .15, .20]
    out = []
    for t in thresholds:
        flagged = p >= t
        tp = int((flagged & (y == 1)).sum())
        fp = int((flagged & (y == 0)).sum())
        nb = tp / n - fp / n * (t / (1 - t))
        nb_all = y.mean() - (1 - y.mean()) * (t / (1 - t))
        out.append({
            "threshold": t,
            "flagged": int(flagged.sum()),
            # Kept, rather than discarded after computing net benefit, because
            # a clinician plans capacity in these units. "Flag 34% of the list
            # to catch 4 in 5 of the deaths" is actionable; a net benefit of
            # 0.02 is not.
            "true_positives": tp,
            "false_positives": fp,
            "number_needed_to_flag": round(int(flagged.sum()) / tp, 1) if tp else None,
            "sensitivity": round(tp / max(int(y.sum()), 1), 4),
            "net_benefit_model": round(float(nb), 5),
            "net_benefit_treat_all": round(float(nb_all), 5),
            "beats_treat_all": bool(nb > nb_all),
            "beats_treat_none": bool(nb > 0),
        })
    return out


def evaluate(y, p, *, label: str = "", n_boot: int = 2000) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    auc = float(roc_auc_score(y, p))
    slope, cil = calibration_slope_intercept(y, p)
    hl_stat, hl_p = hosmer_lemeshow(y, p)
    return {
        "label": label,
        "n": int(len(y)),
        "events": int(y.sum()),
        "prevalence": round(float(y.mean()), 4),
        "roc_auc": round(auc, 4),
        "roc_auc_ci": bootstrap_ci(y, p, lambda a, b: roc_auc_score(a, b), n_boot),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 5),
        "mean_predicted": round(float(p.mean()), 4),
        "observed": round(float(y.mean()), 4),
        "calibration_slope": slope,
        "calibration_in_the_large": cil,
        "hosmer_lemeshow_stat": hl_stat,
        "hosmer_lemeshow_p": hl_p,
    }


def subgroup_report(y, p, groups: dict[str, np.ndarray], *, n_boot: int = 600) -> list[dict]:
    """Per-subgroup discrimination AND calibration.

    Equal AUC across groups is not fairness: a model can rank equally well in
    two groups while systematically under-predicting risk in one of them.
    """
    out = []
    for name, mask in groups.items():
        mask = np.asarray(mask, dtype=bool)
        yy, pp = np.asarray(y)[mask], np.asarray(p)[mask]
        if len(yy) < 30 or yy.min() == yy.max():
            out.append({"group": name, "n": int(len(yy)), "events": int(yy.sum()),
                        "roc_auc": None, "note": "too few for a stable estimate"})
            continue
        row = evaluate(yy, pp, label=name, n_boot=n_boot)
        row["group"] = name
        out.append(row)
    return out
