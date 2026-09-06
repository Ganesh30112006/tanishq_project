"""Does this model help, and who does it fail?

The training battery answers "is the number accurate". That is necessary and
not sufficient. This module answers the questions that decide whether a tool is
defensible in front of a clinician:

* **Coverage** - of the people this would actually be pointed at, how many can
  it score at all?
* **Abstention** - who gets refused, and are they sicker than the people who
  get served? A refusal is a clinical act with a clinical consequence, and an
  accuracy metric computed on the served population cannot see it.
* **Subgroup reliability** - does it hold up in every group, not on average?
* **Clinical utility** - does acting on the output beat the two strategies
  that need no model at all?

Every result is judged against ``acceptance_criteria.py``, which states the
thresholds and the clinical reasoning for each one separately from this code.

Run it::

    python -m intelligence.ml_service.clinical_validation --version 3.0.0

It exits non-zero when a criterion fails, so it can gate a build.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from intelligence.ml_service import acceptance_criteria as AC
from intelligence.ml_service.nhanes_cohort import (
    CVD_CAUSES,
    CYCLES,
    HORIZON_MONTHS,
    PLAUSIBLE,
    build_cycle,
)

warnings.filterwarnings("ignore")

ARTIFACTS = Path(__file__).resolve().parents[1] / "_artifacts"

RETH = {
    1: "Mexican American", 2: "Other Hispanic", 3: "White non-Hispanic",
    4: "Black non-Hispanic", 5: "Other/multiple",
}


# ---------------------------------------------------------------- population
def target_population() -> pd.DataFrame:
    """Everyone this tool would be pointed at - not everyone it can score.

    This is the denominator that matters and the one the training cohort is
    not. The training cohort is, by construction, the people whose required
    measurements all happened to be present and in range; scoring the model on
    that population and calling the result its performance assumes away the
    entire question this module exists to ask.

    So: every adult aged 40-79 who was eligible for mortality linkage and whose
    10-year outcome is known, whether or not any of the model's inputs were
    ever recorded for them.
    """
    df = pd.concat([build_cycle(*c) for c in CYCLES], ignore_index=True)
    df = df.rename(columns={"RIDAGEYR": "age", "BMXBMI": "bmi"})
    df = df[(df.age >= 40) & (df.age <= 79)]
    if "RIDEXPRG" in df.columns:
        df = df[df.RIDEXPRG != 1]
    df = df[df.ELIGSTAT == 1]

    for col, (lo, hi) in PLAUSIBLE.items():
        if col in df.columns:
            bad = df[col].notna() & ((df[col] < lo) | (df[col] > hi))
            df.loc[bad, col] = np.nan

    df = df.dropna(subset=["PERMTH_EXM"])
    df = df[(df.MORTSTAT == 1) | (df.PERMTH_EXM >= HORIZON_MONTHS)]
    df["y"] = (
        (df.MORTSTAT == 1)
        & df.UCOD_LEADING.isin(CVD_CAUSES)
        & (df.PERMTH_EXM <= HORIZON_MONTHS)
    ).astype(int)
    df["is_male"] = (df.RIAGENDR == 1).astype(float)
    df["sex"] = np.where(df.RIAGENDR == 1, "Male", "Female")
    df["ethnicity"] = df.RIDRETH1.map(RETH)
    df["age_band"] = pd.cut(
        df.age, [39, 54, 69, 79], labels=["40-54", "55-69", "70-79"]
    )
    return df.reset_index(drop=True)


# ----------------------------------------------------------------- abstention
def classify_service(df: pd.DataFrame, features: list[str], domain: dict):
    """Why each person would or would not be scored.

    Mirrors what the deployed sufficiency engine does: a required feature that
    is absent blocks, and a present feature outside the model's validated range
    blocks. ``is_male`` is derived from recorded sex and is never estimated.
    """
    needed = [f for f in features if f in df.columns]
    missing = df[needed].isna().any(axis=1)

    breach_side = pd.Series("", index=df.index)
    breach_feature = pd.Series("", index=df.index)
    outside = pd.Series(False, index=df.index)
    for feature in needed:
        bounds = domain.get(feature)
        if not bounds:
            continue
        value = df[feature]
        above = value.notna() & (value > bounds["max"])
        below = value.notna() & (value < bounds["min"])
        for mask, side in ((above, "above"), (below, "below")):
            fresh = mask & ~outside
            breach_side.loc[fresh] = side
            breach_feature.loc[fresh] = feature
            outside |= mask

    out = pd.DataFrame(index=df.index)
    out["missing"] = missing
    out["out_of_domain"] = outside & ~missing
    out["served"] = ~missing & ~outside
    out["breach_feature"] = breach_feature.where(out.out_of_domain, "")
    out["breach_side"] = breach_side.where(out.out_of_domain, "")
    return out


def _rate(frame: pd.DataFrame) -> float:
    return float(frame.y.mean()) if len(frame) else 0.0


def coverage_report(df: pd.DataFrame, service: pd.DataFrame, risk_direction: dict):
    """Coverage, and whether the people turned away are sicker than those served."""
    served, missing = df[service.served], df[service.missing]
    refused = df[~service.served]
    ood = df[service.out_of_domain]

    breaches = []
    if len(ood):
        detail = service[service.out_of_domain]
        for (feature, side), idx in detail.groupby(
            ["breach_feature", "breach_side"]
        ).groups.items():
            group = df.loc[idx]
            # Is this the side the model says carries more risk? A positive
            # coefficient means larger values are riskier, so a breach *above*
            # the validated ceiling is the dangerous direction.
            direction = risk_direction.get(feature, 0.0)
            dangerous = (side == "above" and direction > 0) or (
                side == "below" and direction < 0
            )
            breaches.append({
                "feature": feature, "side": side, "n": int(len(group)),
                "events": int(group.y.sum()), "rate": round(_rate(group), 4),
                "higher_risk_side": bool(dangerous),
            })
    breaches.sort(key=lambda b: -b["rate"])

    served_rate = _rate(served)
    return {
        "target_population": int(len(df)),
        "target_events": int(df.y.sum()),
        "served": int(len(served)),
        "coverage": round(len(served) / len(df), 4) if len(df) else 0.0,
        "refused": int(len(refused)),
        "refused_missing": int(len(missing)),
        "refused_out_of_domain": int(len(ood)),
        "served_event_rate": round(served_rate, 4),
        "refused_event_rate": round(_rate(refused), 4),
        "refused_risk_ratio": (
            round(_rate(refused) / served_rate, 3) if served_rate else None
        ),
        "domain_breaches": breaches,
    }


def refusal_by_group(df: pd.DataFrame, service: pd.DataFrame, column: str):
    rows = []
    for name, idx in df.groupby(column, observed=True).groups.items():
        group = service.loc[idx]
        n = int(len(group))
        refused = int((~group.served).sum())
        rows.append({
            "group": str(name), "n": n, "refused": refused,
            "refusal_rate": round(refused / n, 4) if n else 0.0,
        })
    rows.sort(key=lambda r: r["refusal_rate"])
    return rows


# -------------------------------------------------------------------- utility
def recover_true_positives(row: dict, n: int):
    """How many of the flagged patients actually died, from a decision-curve row.

    Model cards written before ``net_benefit`` began recording true and false
    positives still carry enough to recover them exactly, because net benefit
    is defined as ``tp/n - fp/n * odds`` and ``flagged = tp + fp``. Two
    equations, two unknowns:

        tp = (net_benefit * n + flagged * odds) / (1 + odds)

    This is algebra rather than estimation - but net benefit is stored rounded
    to five decimals, so the result is checked against the nearest whole person
    and abandoned rather than reported if it does not land on one. A capacity
    figure that is quietly half a patient wrong is worse than no figure.
    """
    if row.get("true_positives") is not None:
        return int(row["true_positives"])
    threshold = float(row["threshold"])
    odds = threshold / (1 - threshold)
    tp = (float(row["net_benefit_model"]) * n + int(row["flagged"]) * odds) / (1 + odds)
    nearest = round(tp)
    return nearest if abs(tp - nearest) < 0.4 and nearest >= 0 else None


# ------------------------------------------------------------------ judgement
#: "Could not be assessed" is not the same as "failed". A criterion with no
#: data behind it must not be reported as evidence against the model - but it
#: must not read as a clean pass either, so the observed column says so.
NOT_ASSESSED = "not assessed"


def _check(key, passed, observed, note=""):
    criterion = AC.CRITERIA_BY_KEY[key]
    return {
        "key": key, "passed": bool(passed), "observed": observed,
        "statement": criterion.statement, "basis": criterion.basis, "note": note,
    }


def judge(coverage: dict, groups: dict, metrics: dict, utility: dict,
          directional_refusal_supported: bool):
    """Every criterion, with what was measured against it."""
    results = []

    results.append(_check(
        "coverage.overall", coverage["coverage"] >= AC.MIN_COVERAGE,
        f"{coverage['coverage']:.1%} of {coverage['target_population']:,} people",
    ))

    ratio = coverage["refused_risk_ratio"]
    results.append(_check(
        "coverage.refused_risk_ratio",
        ratio is None or ratio <= AC.MAX_REFUSED_RISK_RATIO,
        f"{ratio}x  (refused {coverage['refused_event_rate']:.2%} vs "
        f"served {coverage['served_event_rate']:.2%})"
        if ratio is not None else f"{NOT_ASSESSED}: no events among served patients",
    ))

    worst_group, worst_ratio = None, None
    for column, rows in groups.items():
        eligible = [r for r in rows if r["n"] >= 300]
        if len(eligible) < 2:
            continue
        best = min(r["refusal_rate"] for r in eligible) or 1e-9
        for row in eligible:
            r = row["refusal_rate"] / best
            if worst_ratio is None or r > worst_ratio:
                worst_ratio, worst_group = r, f"{row['group']} ({column})"
    results.append(_check(
        "coverage.group_disparity",
        worst_ratio is None or worst_ratio <= AC.MAX_GROUP_REFUSAL_RATIO,
        f"{worst_ratio:.2f}x - worst is {worst_group}" if worst_ratio
        else f"{NOT_ASSESSED}: fewer than two groups of 300+ people",
    ))

    dangerous = [b for b in coverage["domain_breaches"] if b["higher_risk_side"]]
    results.append(_check(
        "coverage.no_silent_dangerous_refusal",
        directional_refusal_supported or not dangerous,
        (f"{sum(b['n'] for b in dangerous)} people refused on the higher-risk "
         f"side; directional wording "
         f"{'implemented' if directional_refusal_supported else 'NOT implemented'}"),
    ))

    primary = metrics["primary"]
    lo, hi = primary["roc_auc_ci"]
    results.append(_check(
        "discrimination.above_chance", lo > 0.5,
        f"AUC {primary['roc_auc']} (95% CI {lo}-{hi})",
    ))

    vs_age = metrics["vs_age_alone"]
    results.append(_check(
        "discrimination.beats_age", metrics["beats_age_alone"],
        f"{vs_age['mean_diff']:+.4f} (95% CI {vs_age['ci'][0]:+.4f} to "
        f"{vs_age['ci'][1]:+.4f})",
    ))

    weak = [
        s for s in metrics["subgroup"]
        if s.get("events", 0) >= AC.MIN_SUBGROUP_EVENTS
        and s.get("roc_auc_ci") and s["roc_auc_ci"][0] <= 0.5
    ]
    scored = [
        s for s in metrics["subgroup"] if s.get("events", 0) >= AC.MIN_SUBGROUP_EVENTS
    ]
    worst = min(scored, key=lambda s: s["roc_auc_ci"][0]) if scored else None
    results.append(_check(
        "discrimination.subgroup_above_chance", not weak,
        (f"weakest is {worst['group']}, AUC {worst['roc_auc']} "
         f"(lower bound {worst['roc_auc_ci'][0]})") if worst
        else f"{NOT_ASSESSED}: no subgroup with {AC.MIN_SUBGROUP_EVENTS}+ events",
    ))

    slope = primary["calibration_slope"]
    slope_lo, slope_hi = AC.CALIBRATION_SLOPE_RANGE
    results.append(_check(
        "calibration.slope", slope_lo <= slope <= slope_hi, f"slope {slope}",
    ))

    worst_err, worst_name = None, None
    for s in scored:
        observed, predicted = s.get("observed"), s.get("mean_predicted")
        if not observed:
            continue
        err = abs(observed - predicted) / observed
        if worst_err is None or err > worst_err:
            worst_err, worst_name = err, s["group"]
    results.append(_check(
        "calibration.subgroup_error",
        worst_err is None or worst_err <= AC.MAX_SUBGROUP_RELATIVE_ERROR,
        f"worst is {worst_name}, {worst_err:.1%} relative error" if worst_err is not None
        else f"{NOT_ASSESSED}: no subgroup with {AC.MIN_SUBGROUP_EVENTS}+ events",
    ))

    results.append(_check(
        "utility.beats_default_strategies", utility["beats_both"],
        (f"at {utility['threshold']:.0%}: net benefit {utility['net_benefit_model']} "
         f"vs treat-all {utility['net_benefit_treat_all']}"),
    ))
    return results


# ------------------------------------------------------------------------ cli
def main(version: str = "3.0.0") -> int:
    card_path = ARTIFACTS / f"cvd-{version}.meta.json"
    if not card_path.exists():
        print(f"No model card at {card_path}. Train it first.")
        return 2
    card = json.loads(card_path.read_text())
    metrics = card["validation_metrics"]
    features = card["feature_order"]
    domain = card["domain"]
    risk_direction = metrics.get("standardised_coefficients", {})

    print(f"=== clinical validation: cvd-{version} ===")
    print(f"criteria: {AC.CRITERIA_VERSION}   decision threshold: "
          f"{AC.DECISION_THRESHOLD:.0%} 10-year risk of cardiovascular death")
    print(f"features: {features}")

    population = target_population()
    service = classify_service(population, features, domain)
    coverage = coverage_report(population, service, risk_direction)
    groups = {
        column: refusal_by_group(population, service, column)
        for column in ("sex", "age_band", "ethnicity")
    }

    print("\n--- coverage of the target population ---")
    print(f"  target population           {coverage['target_population']:>7,}  "
          f"({coverage['target_events']:,} deaths)")
    print(f"  can be scored               {coverage['served']:>7,}  "
          f"({coverage['coverage']:.1%})")
    print(f"  refused, input missing      {coverage['refused_missing']:>7,}")
    print(f"  refused, outside range      {coverage['refused_out_of_domain']:>7,}")
    print(f"  event rate served           {coverage['served_event_rate']:>7.2%}")
    print(f"  event rate refused          {coverage['refused_event_rate']:>7.2%}"
          f"   ({coverage['refused_risk_ratio']}x)")

    if coverage["domain_breaches"]:
        print("\n--- who falls outside the validated range ---")
        print(f"  {'feature':<16} {'side':<6} {'n':>5} {'events':>7} {'rate':>8}  flag")
        for b in coverage["domain_breaches"]:
            flag = "HIGHER-RISK SIDE" if b["higher_risk_side"] else ""
            print(f"  {b['feature']:<16} {b['side']:<6} {b['n']:>5} "
                  f"{b['events']:>7} {b['rate']:>8.2%}  {flag}")

    print("\n--- refusal rate by group ---")
    for column, rows in groups.items():
        print(f"  {column}")
        for row in rows:
            print(f"    {row['group']:<20} {row['n']:>6,}  refused "
                  f"{row['refused']:>5,}  {row['refusal_rate']:>7.2%}")

    # Utility is measured on the held-out test predictions the training run
    # recorded, so this does not refit anything.
    decision_curve = {row["threshold"]: row for row in metrics["decision_curve"]}
    nearest = min(decision_curve, key=lambda t: abs(t - AC.DECISION_THRESHOLD))
    row = decision_curve[nearest]
    n_test = metrics["n_test"]
    events_test = metrics["events_test"]
    true_positives = recover_true_positives(row, n_test)
    utility = {
        "threshold": nearest,
        "flagged": row["flagged"],
        "flagged_share": round(row["flagged"] / n_test, 4),
        "true_positives": true_positives,
        "number_needed_to_flag": (
            round(row["flagged"] / true_positives, 1) if true_positives else None
        ),
        "sensitivity": (
            round(true_positives / events_test, 4) if true_positives else None
        ),
        "net_benefit_model": row["net_benefit_model"],
        "net_benefit_treat_all": row["net_benefit_treat_all"],
        "beats_both": bool(row["beats_treat_all"] and row["beats_treat_none"]),
    }
    print(f"\n--- clinical utility at a {nearest:.0%} decision threshold ---")
    print(f"  flagged {row['flagged']:,} of {n_test:,} "
          f"({utility['flagged_share']:.1%} of the list)")
    if true_positives:
        print(f"  caught {true_positives} of the {events_test} people who died "
              f"({utility['sensitivity']:.1%})")
        print(f"  {utility['number_needed_to_flag']} flagged per death caught")
    print(f"  net benefit  model {row['net_benefit_model']:+.5f}   "
          f"treat-all {row['net_benefit_treat_all']:+.5f}   treat-none 0.00000")

    directional = _directional_refusal_supported()
    results = judge(coverage, groups, metrics, utility, directional)

    print(f"\n=== acceptance criteria ({AC.CRITERIA_VERSION}) ===")
    failed = [r for r in results if not r["passed"]]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] {r['key']:<44} {r['observed']}")
    print()
    if failed:
        print(f"  {len(failed)} of {len(results)} criteria FAILED:")
        for r in failed:
            print(f"    - {r['key']}")
            print(f"        {r['statement']}")
            print(f"        why it matters: {r['basis']}")
    else:
        print(f"  all {len(results)} criteria met.")

    report_path = ARTIFACTS / f"cvd-{version}.clinical.json"
    report_path.write_text(json.dumps({
        "criteria_version": AC.CRITERIA_VERSION,
        "model_version": version,
        "decision_threshold": AC.DECISION_THRESHOLD,
        "coverage": coverage,
        "refusal_by_group": groups,
        "utility": utility,
        "criteria": results,
        "passed": not failed,
    }, indent=2, default=str))
    print(f"\nwrote {report_path}")
    return 1 if failed else 0


def _directional_refusal_supported() -> bool:
    """Does the served system distinguish a dangerous breach from a harmless one?

    Checked against the running code rather than assumed, so this criterion
    cannot pass because someone remembered it differently.
    """
    try:
        from apps.risk.sufficiency import SufficiencyReport
    except Exception:  # noqa: BLE001 - Django may not be configured here
        return False
    return hasattr(SufficiencyReport, "domain_breaches") or (
        "domain_breaches" in getattr(SufficiencyReport, "__slots__", ())
    )


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="3.0.0")
    sys.exit(main(ap.parse_args().version))
