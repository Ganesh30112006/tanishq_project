"""Run the shipped model against a population it has never seen.

Everything else in this pipeline is measured on NHANES 1999-2010: the model was
fitted on the first four cycles and tested on the last two. Those are different
people in a different period, which is a real external validation - but they are
the same survey, the same country, and the same measurement protocol.

This module scores the model on **NHANES 2011-2014**, which no part of training,
calibration or model selection has ever touched, and reports separately for the
**Non-Hispanic Asian** participants in it. That group is the nearest publicly
available proxy for the population this system is intended to serve, and it is
one the model is close to blind to: the training cycles coded ethnicity with
``RIDRETH1``, which has no Asian category at all, so those participants were
folded into "Other race including multi-racial".

## What this can and cannot establish

The public mortality linkage ends in December 2019, so a 2013 examination has at
most six years of follow-up. The 10-year outcome the model was fitted for cannot
be observed here at all. This validation therefore uses a **5-year** horizon,
and that mismatch decides what may honestly be claimed:

* **Discrimination transfers.** Whether the model ranks a higher-risk person
  above a lower-risk one does not depend on the length of the window, so ROC-AUC
  measured at 5 years is comparable with the 10-year figure.
* **Calibration does not transfer, and is not reported.** Five-year risk is
  roughly half of ten-year risk by construction. A calibration slope computed by
  comparing 10-year predictions against 5-year outcomes would be badly wrong and
  would look like a finding. The one thing that can honestly be shown is that
  observed risk still *rises* across predicted deciles, which is a statement
  about ordering rather than level, and it is labelled as such.
* **Coverage and abstention transfer**, because they compare the served and
  refused groups on the same horizon as each other.

Run it::

    python -m intelligence.ml_service.external_validation --version 3.1.0
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from intelligence.ml_service import acceptance_criteria as AC
from intelligence.ml_service import cohort_contract as CC
from intelligence.ml_service.clinical_validation import (
    classify_service,
    coverage_report,
    refusal_by_group,
)
from intelligence.ml_service.evaluation import bootstrap_ci
from intelligence.ml_service.nhanes_cohort import (
    CVD_CAUSES,
    PLAUSIBLE,
    _first_col,
    _mortality,
    _xpt,
)

warnings.filterwarnings("ignore")

ARTIFACTS = Path(__file__).resolve().parents[1] / "_artifacts"

#: Never used for fitting, calibration or model selection.
EXTERNAL_CYCLES = [(2011, "_G"), (2013, "_H")]

#: What this population is, declared before it is scored. The horizon, the
#: outcome definition and the caveats come from here rather than from the code
#: below, so that a second cohort declares the same things in the same shape.
SPEC = CC.CohortSpec(
    key="nhanes-2011-2014",
    label="NHANES 2011-2014, US adults aged 40-79",
    provenance=(
        "CDC National Health and Nutrition Examination Survey, cycles G and H, "
        "linked to the NCHS public-use mortality file through December 2019"
    ),
    country="United States",
    examined="2011-2014",
    outcome="death from heart disease or cerebrovascular disease",
    outcome_source=(
        "NCHS linked mortality file, underlying cause coded to the leading-cause "
        "recode; ascertained by national death-record linkage, not by follow-up "
        "contact"
    ),
    horizon_months=60,
    ethnicity_scheme=(
        "RIDRETH3, which adds a Non-Hispanic Asian category that RIDRETH1 - used "
        "in the development cycles - did not have"
    ),
    role=CC.EXTERNAL,
    consent_basis="public-use de-identified survey data released by CDC/NCHS",
    caveats=(
        "Follow-up ends December 2019, so only 5 of the model's 10 years can be "
        "observed. Calibration is therefore not reportable here.",
        "Non-Hispanic Asian participants are US residents, and the category "
        "aggregates East, Southeast and South Asian origins. It is the nearest "
        "available proxy for the intended population and it is not that "
        "population.",
    ),
)

#: Five years, not ten. See the module docstring for what that costs.
HORIZON_MONTHS = SPEC.horizon_months

#: RIDRETH3, available from 2011. The training cycles used RIDRETH1, which has
#: no Asian category - code 6 below simply did not exist for the model.
RETH3 = {
    1: "Mexican American", 2: "Other Hispanic", 3: "White non-Hispanic",
    4: "Black non-Hispanic", 6: "Asian non-Hispanic", 7: "Other/multiple",
}

#: Below this many deaths, an estimate is reported but no conclusion is drawn.
MIN_EVENTS_FOR_A_CONCLUSION = 25


def _cycle(year: int, suffix: str) -> pd.DataFrame:
    demo = _xpt(year, f"DEMO{suffix}")
    columns = ["SEQN", "RIAGENDR", "RIDAGEYR", "RIDRETH3"]
    if "RIDEXPRG" in demo.columns:
        columns.append("RIDEXPRG")
    df = demo[columns].copy()

    bpx = _xpt(year, f"BPX{suffix}")
    systolic = [c for c in ("BPXSY1", "BPXSY2", "BPXSY3", "BPXSY4") if c in bpx.columns]
    bp = bpx[["SEQN"] + systolic].copy()
    bp[systolic] = bp[systolic].replace(0, np.nan)   # a zero is a failed reading
    bp["systolic_bp"] = bp[systolic].mean(axis=1, skipna=True)

    smq = _xpt(year, f"SMQ{suffix}")
    ever = _first_col(smq, "SMQ020")
    now = _first_col(smq, "SMQ040")
    smoking = pd.DataFrame({"SEQN": smq["SEQN"]})
    smoking["current_smoker"] = (
        np.where(now.isin([1, 2]), 1.0, np.where((now == 3) | (ever == 2), 0.0, np.nan))
        if now is not None else np.nan
    )

    df = df.merge(bp[["SEQN", "systolic_bp"]], on="SEQN", how="left")
    df = df.merge(smoking, on="SEQN", how="left")
    df = df.merge(_mortality(year), on="SEQN", how="left")
    df["cycle"] = year
    return df


def external_cohort() -> pd.DataFrame:
    """NHANES 2011-2014 adults aged 40-79, with a 5-year outcome."""
    df = pd.concat([_cycle(*c) for c in EXTERNAL_CYCLES], ignore_index=True)
    df = df.rename(columns={"RIDAGEYR": "age"})
    steps = [("all participants, 2 cycles", len(df))]

    df = df[(df.age >= 40) & (df.age <= 79)]
    steps.append(("aged 40-79 at examination", len(df)))
    if "RIDEXPRG" in df.columns:
        df = df[df.RIDEXPRG != 1]
        steps.append(("not pregnant at examination", len(df)))
    df = df[df.ELIGSTAT == 1]
    steps.append(("eligible for mortality linkage", len(df)))

    for column, (low, high) in PLAUSIBLE.items():
        if column in df.columns:
            bad = df[column].notna() & ((df[column] < low) | (df[column] > high))
            df.loc[bad, column] = np.nan

    df = df.dropna(subset=["PERMTH_EXM"])
    died = df.MORTSTAT == 1
    df = df[died | (df.PERMTH_EXM >= HORIZON_MONTHS)]
    steps.append((f"observed to {HORIZON_MONTHS} months or died", len(df)))

    df["y"] = (
        (df.MORTSTAT == 1)
        & df.UCOD_LEADING.isin(CVD_CAUSES)
        & (df.PERMTH_EXM <= HORIZON_MONTHS)
    ).astype(int)
    df["is_male"] = (df.RIAGENDR == 1).astype(float)
    df["sex"] = np.where(df.RIAGENDR == 1, "Male", "Female")
    df["ethnicity"] = df.RIDRETH3.map(RETH3)
    df["age_band"] = pd.cut(df.age, [39, 54, 69, 79], labels=["40-54", "55-69", "70-79"])

    print("=== external cohort derivation ===")
    previous = None
    derivation = []
    for label, n in steps:
        delta = "" if previous is None else f"  (-{previous - n:,})"
        print(f"  {n:>7,}  {label}{delta}")
        derivation.append({
            "step": label, "remaining": int(n),
            "removed": None if previous is None else int(previous - n),
        })
        previous = n
    df = df.reset_index(drop=True)
    # Who was excluded is a question the record has to be able to answer on its
    # own. Printing the ladder and throwing it away means the only place the
    # answer ever existed was a terminal scrollback.
    df.attrs["derivation"] = derivation
    return df


CC.register(SPEC, external_cohort)


def load_model(version: str):
    import joblib

    bundle = joblib.load(ARTIFACTS / f"cvd-{version}.joblib")
    return bundle["estimator"], bundle["feature_order"]


def _auc(y, p):
    from sklearn.metrics import roc_auc_score

    y = np.asarray(y)
    if y.min() == y.max():
        return None, None
    return float(roc_auc_score(y, p)), bootstrap_ci(y, p, roc_auc_score)


def discrimination_by_group(df: pd.DataFrame, p, column: str):
    rows = []
    for name, index in df.groupby(column, observed=True).groups.items():
        position = df.index.get_indexer(index)
        y = df.loc[index, "y"].to_numpy(int)
        auc, ci = _auc(y, np.asarray(p)[position])
        rows.append({
            "group": str(name), "n": int(len(y)), "events": int(y.sum()),
            "event_rate": round(float(y.mean()), 4) if len(y) else None,
            "roc_auc": round(auc, 4) if auc is not None else None,
            "roc_auc_ci": ci,
            "conclusion_supported": bool(y.sum() >= MIN_EVENTS_FOR_A_CONCLUSION),
        })
    rows.sort(key=lambda r: -r["n"])
    return rows


def risk_gradient(y, p, bins: int = 5):
    """Observed 5-year risk across predicted-risk bands.

    This is NOT calibration. The predictions are 10-year risks and the outcomes
    are 5-year, so the levels cannot be compared and no slope is computed. What
    it does show is whether the ordering still holds in a population the model
    has never seen - which is a real and separate question.
    """
    y, p = np.asarray(y), np.asarray(p)
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    index = np.clip(np.digitize(p, edges[1:-1]), 0, len(edges) - 2)
    rows = []
    for b in range(len(edges) - 1):
        mask = index == b
        rows.append({
            "band": b + 1, "n": int(mask.sum()),
            "events": int(y[mask].sum()),
            "mean_predicted_10y": round(float(p[mask].mean()), 4) if mask.any() else None,
            "observed_5y": round(float(y[mask].mean()), 4) if mask.any() else None,
        })
    return rows


MODEL_HORIZON_MONTHS = 120


def main(version: str = "3.1.0", cohort: str = "nhanes-2011-2014") -> int:
    card_path = ARTIFACTS / f"cvd-{version}.meta.json"
    if not card_path.exists():
        print(f"No model card at {card_path}. Train it first.")
        return 2
    card = json.loads(card_path.read_text())
    internal = card["validation_metrics"]["primary"]
    domain = card["domain"]
    direction = card["validation_metrics"].get("standardised_coefficients", {})

    spec, loader = CC.get(cohort)
    reportable, refusal_reason = CC.calibration_reportable(spec, MODEL_HORIZON_MONTHS)

    print(f"=== external validation: cvd-{version} on {spec.key} ===")
    print(f"population : {spec.label} ({spec.country}, examined {spec.examined})")
    print(f"provenance : {spec.provenance}")
    print(f"outcome    : {spec.outcome}, within {spec.horizon_months} months")
    print(f"ascertained: {spec.outcome_source}")
    print(f"role       : {spec.role}")
    for caveat in spec.caveats:
        print(f"caveat     : {caveat}")

    df = loader()
    estimator, features = load_model(version)

    # The contract is checked before anything is scored. A report produced from
    # an unchecked frame looks exactly like a real one, which is what makes it
    # dangerous.
    problems = CC.validate_cohort(df, spec, features)
    if problems:
        print("\n=== cohort contract ===")
        print(CC.describe_problems(problems))
        if any(p.severity == "hard" for p in problems):
            print("\nHard problems: refusing to score this cohort.")
            return 2
        print("Soft problems: the questions above cannot be answered for this "
              "cohort and are reported as unanswered rather than skipped.")

    service = classify_service(df, features, domain)
    coverage = coverage_report(df, service, direction)
    print("\n=== coverage on the unseen population ===")
    print(f"  target population       {coverage['target_population']:>7,}  "
          f"({coverage['target_events']:,} deaths in 5 years)")
    print(f"  can be scored           {coverage['served']:>7,}  "
          f"({coverage['coverage']:.1%})")
    print(f"  refused, input missing  {coverage['refused_missing']:>7,}")
    print(f"  refused, outside range  {coverage['refused_out_of_domain']:>7,}")
    print(f"  event rate served       {coverage['served_event_rate']:>7.2%}")
    print(f"  event rate refused      {coverage['refused_event_rate']:>7.2%}"
          f"  ({coverage['refused_risk_ratio']}x)")
    for breach in coverage["domain_breaches"]:
        flag = "HIGHER-RISK SIDE" if breach["higher_risk_side"] else ""
        print(f"    {breach['feature']:<14} {breach['side']:<6} n={breach['n']:<5} "
              f"rate {breach['rate']:.2%}  {flag}")

    served = df[service.served].reset_index(drop=True)
    probabilities = estimator.predict_proba(served[features].to_numpy(float))[:, 1]
    y = served.y.to_numpy(int)

    auc, ci = _auc(y, probabilities)
    print("\n=== discrimination on the unseen population ===")
    print(f"  n = {len(y):,}   deaths = {int(y.sum())}   "
          f"rate = {y.mean():.2%} over 5 years")
    print(f"  ROC-AUC {auc:.4f}  (95% CI {ci[0]}-{ci[1]})")
    print(f"  internal test set, 10-year outcome: {internal['roc_auc']} "
          f"(95% CI {internal['roc_auc_ci'][0]}-{internal['roc_auc_ci'][1]})")
    # Overlapping confidence intervals are a weak test and must not be dressed
    # up as a conclusion. Non-overlap would be evidence of degradation; overlap
    # is not evidence of transfer, especially at this many events. Report what
    # the interval is actually compatible with instead.
    overlap = ci[0] <= internal["roc_auc_ci"][1] and internal["roc_auc_ci"][0] <= ci[1]
    drop = internal["roc_auc"] - auc
    if not overlap:
        print(f"  intervals do NOT overlap: discrimination is DEGRADED on this "
              f"population ({drop:+.4f})")
    else:
        direction = "lower than" if drop > 0 else "higher than"
        print(f"  point estimate is {abs(drop):.4f} {direction} the internal "
              f"figure, and the intervals overlap.")
        print(f"  That is not evidence of degradation. At {int(y.sum())} deaths it "
              f"is not evidence of")
        print("  transfer either - this interval is equally compatible with "
              "discrimination")
        print(f"  as low as {ci[0]}, which would be materially worse. The study is "
              f"underpowered")
        print("  to tell those apart.")

    print("\n=== discrimination by group (the transportability question) ===")
    print(f"  {'group':<22} {'n':>6} {'deaths':>7} {'rate':>7} {'AUC':>8} "
          f"{'95% CI':>18}  conclusion")
    ethnic = discrimination_by_group(served, probabilities, "ethnicity")
    for row in ethnic:
        auc_text = f"{row['roc_auc']:.4f}" if row["roc_auc"] is not None else "-"
        ci_text = (f"{row['roc_auc_ci'][0]}-{row['roc_auc_ci'][1]}"
                   if row["roc_auc_ci"] else "-")
        verdict = "supported" if row["conclusion_supported"] else "TOO FEW DEATHS"
        print(f"  {row['group']:<22} {row['n']:>6,} {row['events']:>7} "
              f"{row['event_rate']:>7.2%} {auc_text:>8} {ci_text:>18}  {verdict}")

    print("\n=== does the ordering still hold? (NOT calibration) ===")
    print("  Predictions are 10-year risks; outcomes are 5-year. The levels are")
    print("  not comparable and no slope is computed. Only the gradient is read.")
    print(f"  {'band':>5} {'n':>6} {'deaths':>7} {'mean predicted 10y':>20} "
          f"{'observed 5y':>13}")
    gradient = risk_gradient(y, probabilities)
    for row in gradient:
        print(f"  {row['band']:>5} {row['n']:>6,} {row['events']:>7} "
              f"{row['mean_predicted_10y']:>20.4f} {row['observed_5y']:>13.4f}")
    rising = all(
        gradient[i]["observed_5y"] <= gradient[i + 1]["observed_5y"]
        for i in range(len(gradient) - 1)
    )
    print(f"  monotonically rising: {rising}")

    # --- which development-cohort findings actually replicate? -----------
    print("\n=== what replicates from the development cohort ===")
    replication = []

    ratio = coverage["refused_risk_ratio"]
    held = ratio is not None and ratio <= AC.MAX_REFUSED_RISK_RATIO
    replication.append({
        "finding": "refused patients are not markedly sicker than served ones",
        "development": "1.36x - within the 1.5x ceiling",
        "external": f"{ratio}x",
        "replicates": bool(held),
    })

    # In development the low-blood-pressure breach looked harmless: 4.89%
    # against 4.92% for the served population. Check whether that holds.
    served_rate = coverage["served_event_rate"] or 1e-9
    for breach in coverage["domain_breaches"]:
        rate_ratio = breach["rate"] / served_rate
        benign = not breach["higher_risk_side"]
        replication.append({
            "finding": (f"{breach['feature']} {breach['side']} the validated range "
                        f"is {'benign' if benign else 'the higher-risk side'}"),
            "development": "4.89% vs 4.92% served - benign" if benign else
                           "16.06% vs 4.92% served - dangerous",
            "external": (f"{breach['rate']:.2%} vs {served_rate:.2%} served "
                         f"({rate_ratio:.1f}x, n={breach['n']}, "
                         f"{breach['events']} deaths)"),
            "replicates": bool(benign == (rate_ratio <= 1.5)),
        })

    for row in replication:
        mark = "HOLDS" if row["replicates"] else "DOES NOT HOLD"
        print(f"  [{mark:>13}] {row['finding']}")
        print(f"                  development: {row['development']}")
        print(f"                  external   : {row['external']}")

    broken = [r for r in replication if not r["replicates"]]
    if broken:
        print("\n  A finding that does not replicate is not automatically wrong -")
        print("  some of these rest on very few deaths. It does mean the")
        print("  development cohort was not enough to establish it, and that any")
        print("  wording built on it must not claim more than it has earned.")

    report = {
        "model_version": version,
        "replication": replication,
        "cohort": {
            "key": spec.key, "label": spec.label, "provenance": spec.provenance,
            "country": spec.country, "examined": spec.examined,
            "outcome": spec.outcome, "outcome_source": spec.outcome_source,
            "ethnicity_scheme": spec.ethnicity_scheme, "role": spec.role,
            "consent_basis": spec.consent_basis, "caveats": list(spec.caveats),
        },
        "derivation": df.attrs.get("derivation", []),
        # The claim attached to the population name is the role the cohort
        # declared, not a phrase typed next to it. A cohort that was used in
        # development must never be described as if it had not been.
        "population": (
            f"{spec.label}, "
            + {CC.EXTERNAL: "never used in development",
               CC.INTERNAL_TEST: "held out from fitting but the same survey and "
                                 "measurement protocol as development",
               CC.DEVELOPMENT: "USED IN DEVELOPMENT - this is not an external "
                               "validation"}[spec.role]
        ),
        "horizon_months": spec.horizon_months,
        "model_horizon_months": MODEL_HORIZON_MONTHS,
        "calibration_reported": reportable,
        "calibration_not_reported_because": refusal_reason,
        "coverage": coverage,
        "refusal_by_group": {
            column: refusal_by_group(df, service, column)
            for column in ("sex", "age_band", "ethnicity")
        },
        "discrimination": {
            "n": int(len(y)), "events": int(y.sum()),
            "roc_auc": round(auc, 4), "roc_auc_ci": ci,
            "internal_roc_auc": internal["roc_auc"],
            "internal_roc_auc_ci": internal["roc_auc_ci"],
            "intervals_overlap": bool(overlap),
        },
        "discrimination_by_ethnicity": ethnic,
        "risk_gradient": gradient,
        "gradient_monotonic": bool(rising),
    }
    destination = ARTIFACTS / f"cvd-{version}.external.json"
    destination.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwrote {destination}")

    underpowered = [r["group"] for r in ethnic if not r["conclusion_supported"]]
    if underpowered:
        print("\n=== what this run does NOT establish ===")
        print("  Too few deaths to support a conclusion for: "
              + ", ".join(underpowered))
        print(f"  ({MIN_EVENTS_FOR_A_CONCLUSION} deaths is the floor used here.)")
        print("  These are reported so the gap is visible, not so it can be read")
        print("  as reassurance. An interval this wide is compatible with the")
        print("  model working well and with it not working at all.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="3.1.0")
    parser.add_argument("--cohort", default="nhanes-2011-2014",
                        choices=CC.registered())
    args = parser.parse_args()
    sys.exit(main(args.version, args.cohort))
