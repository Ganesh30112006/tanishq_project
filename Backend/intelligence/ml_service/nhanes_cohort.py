"""Build a real CVD analytic cohort from NHANES + the NCHS linked mortality files.

Design decisions, stated so a reviewer can disagree with them explicitly:

* **Population** - adults aged 40-79 at examination. This is the age band the
  established CVD risk equations are built and validated for; below 40 ten-year
  event counts are too small to fit, above 80 competing mortality dominates.
* **Outcome** - death with an underlying cause of *diseases of heart* (NCHS
  leading-cause recode 001) or *cerebrovascular disease* (005), occurring
  within 120 months of the examination. This is a hard, adjudicated,
  death-certificate endpoint - not a proxy and not self-reported.
* **Censoring** - participants still alive with under 120 months of follow-up
  have not been observed long enough to know their 10-year status, so they are
  excluded rather than silently counted as non-events.
* **Competing risk** - death from a non-CVD cause inside the window is counted
  as a non-event in the primary analysis. That is the conventional binary
  framing and it biases absolute risk downward; ``--drop-competing`` runs the
  sensitivity analysis that excludes them.
* **Features** - in the units the application stores (mmol/L for glucose and
  HDL, mmol/mol for HbA1c), so the artifact is a drop-in replacement.
* **Glycaemic marker** - ``--sample fasting`` requires fasting glucose, which
  NHANES measures only in the morning subsample; that is roughly half the
  examined sample and is the single largest exclusion in the derivation.
  ``--sample full`` requires HbA1c instead, which is measured on everyone and
  needs no fast. The full-sample cohort is about twice as large, and since the
  binding limit on every conclusion here is the number of *events*, that is the
  difference between "cannot be shown to beat age" and an answer.

Sex, ethnicity, survey cycle and the fasting weight are carried through for
subgroup and survey-representativeness reporting. They are NOT model inputs.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

RAW = Path(__file__).resolve().parents[1] / "_data" / "raw"
OUT = Path(__file__).resolve().parents[1] / "_data" / "cohort.parquet"

# (start_year, suffix, hdl_file, glucose_file, hba1c_file)
CYCLES = [
    (1999, "",   "LAB13",  "LAB10AM", "LAB10"),
    (2001, "_B", "L13_B",  "L10AM_B", "L10_B"),
    (2003, "_C", "L13_C",  "L10AM_C", "L10_C"),
    (2005, "_D", "HDL_D",  "GLU_D",   "GHB_D"),
    (2007, "_E", "HDL_E",  "GLU_E",   "GHB_E"),
    (2009, "_F", "HDL_F",  "GLU_F",   "GHB_F"),
]

# NHANES publishes glycohemoglobin as NGSP %. The application's canonical unit
# for hba1c is IFCC mmol/mol. These constants are asserted against
# apps/common/units.py by tests/integration/test_nhanes_model.py: if the two
# ever drift apart the model would be fitted on one scale and served another,
# which is silent and produces confidently wrong risk.
HBA1C_PCT_TO_MMOL_MOL = (10.929, -23.49735)

MORT_LAYOUT = [
    ("SEQN", 1, 6), ("ELIGSTAT", 15, 15), ("MORTSTAT", 16, 16),
    ("UCOD_LEADING", 17, 19), ("DIABETES", 20, 20), ("HYPERTEN", 21, 21),
    ("PERMTH_INT", 43, 45), ("PERMTH_EXM", 46, 48),
]
# Physiologic possibility, not outlier trimming. These bounds are deliberately
# far wider than any clinical reference range: everything outside them is an
# assay artefact or a transcription error rather than a person. NHANES really
# does publish a glycohemoglobin of 2.0% (-1.6 mmol/mol after conversion), which
# is not a blood sugar any living patient has; a haemoglobin variant defeats the
# assay and the result is reported anyway.
#
# Two reasons to drop these rather than keep them. A standardised value that far
# from the mean is a leverage point that bends the fitted coefficients, and the
# served ``valid_domain`` gate is derived from these same percentiles - so
# training on impossible values quietly widens the gate that is supposed to
# refuse impossible values from real patients.
PLAUSIBLE = {
    "systolic_bp": (60.0, 260.0),      # mmHg
    "bmi": (12.0, 70.0),               # kg/m2
    "hdl": (0.3, 4.0),                 # mmol/L
    "glucose": (2.0, 35.0),            # mmol/L
    "hba1c": (20.0, 200.0),            # mmol/mol, about 4.0% to 20.5% NGSP
}

CVD_CAUSES = {1, 5}          # 001 diseases of heart, 005 cerebrovascular
HORIZON_MONTHS = 120


def _xpt(year: int, name: str) -> pd.DataFrame:
    return pd.read_sas(RAW / str(year) / f"{name}.xpt", format="xport")


def _first_col(df: pd.DataFrame, *names: str) -> pd.Series | None:
    for n in names:
        if n in df.columns:
            return df[n]
    return None


def _mortality(year: int) -> pd.DataFrame:
    rows = []
    for line in (RAW / str(year) / "mortality.dat").read_text().splitlines():
        line = line.ljust(48)
        rec = {}
        for name, a, b in MORT_LAYOUT:
            raw = line[a - 1:b].strip()
            rec[name] = np.nan if raw in ("", ".") else float(raw)
        rows.append(rec)
    return pd.DataFrame(rows)


def build_cycle(year: int, suf: str, hdl_file: str, glu_file: str,
                a1c_file: str) -> pd.DataFrame:
    demo_raw = _xpt(year, f"DEMO{suf}")
    demo_cols = ["SEQN", "RIAGENDR", "RIDAGEYR", "RIDRETH1", "SDDSRVYR"]
    for optional in ("RIDEXPRG", "WTMEC2YR"):
        if optional in demo_raw.columns:
            demo_cols.append(optional)
    demo = demo_raw[demo_cols]
    bmx = _xpt(year, f"BMX{suf}")[["SEQN", "BMXBMI"]]

    bpx_all = _xpt(year, f"BPX{suf}")
    sys_cols = [c for c in ("BPXSY1", "BPXSY2", "BPXSY3", "BPXSY4") if c in bpx_all.columns]
    bp = bpx_all[["SEQN"] + sys_cols].copy()
    # A recorded zero is a failed reading, not a blood pressure.
    bp[sys_cols] = bp[sys_cols].replace(0, np.nan)
    bp["systolic_bp"] = bp[sys_cols].mean(axis=1, skipna=True)
    bp = bp[["SEQN", "systolic_bp"]]

    hdl_raw = _xpt(year, hdl_file)
    hdl = pd.DataFrame({
        "SEQN": hdl_raw["SEQN"],
        "hdl": _first_col(hdl_raw, "LBDHDLSI", "LBDHDDSI"),   # mmol/L
    })
    # Total cholesterol travels with HDL in the early cycles and in its own
    # file (TCHOL_*) from 2005; absent is fine, it is an optional feature.
    tc = _first_col(hdl_raw, "LBDTCSI")
    if tc is None:
        try:
            tchol_raw = _xpt(year, f"TCHOL{suf}")
            tc_df = pd.DataFrame({"SEQN": tchol_raw["SEQN"],
                                  "total_cholesterol": _first_col(tchol_raw, "LBDTCSI")})
        except FileNotFoundError:
            tc_df = pd.DataFrame({"SEQN": hdl_raw["SEQN"], "total_cholesterol": np.nan})
    else:
        tc_df = pd.DataFrame({"SEQN": hdl_raw["SEQN"], "total_cholesterol": tc})

    glu_raw = _xpt(year, glu_file)
    glu = pd.DataFrame({
        "SEQN": glu_raw["SEQN"],
        "glucose": _first_col(glu_raw, "LBXGLUSI", "LBDGLUSI"),  # mmol/L
        "fasting_weight": _first_col(glu_raw, "WTSAF2YR"),
    })

    # Glycohemoglobin, measured on the whole examined sample - no fast needed.
    a1c_raw = _xpt(year, a1c_file)
    factor, offset = HBA1C_PCT_TO_MMOL_MOL
    a1c = pd.DataFrame({
        "SEQN": a1c_raw["SEQN"],
        "hba1c": _first_col(a1c_raw, "LBXGH") * factor + offset,   # mmol/mol
    })

    # Smoking: SMQ020 = ever smoked 100 cigarettes; SMQ040 = smokes now.
    smq_raw = _xpt(year, f"SMQ{suf}")
    ever = _first_col(smq_raw, "SMQ020")
    now = _first_col(smq_raw, "SMQ040")
    smq = pd.DataFrame({"SEQN": smq_raw["SEQN"]})
    smq["ever_smoker"] = np.where(ever == 1, 1.0, np.where(ever == 2, 0.0, np.nan))
    if now is not None:
        smq["current_smoker"] = np.where(
            now.isin([1, 2]), 1.0, np.where((now == 3) | (ever == 2), 0.0, np.nan)
        )
    else:
        smq["current_smoker"] = np.nan

    # Diabetes: DIQ010 = ever told by a doctor. 3 = borderline, kept separate.
    diq_raw = _xpt(year, f"DIQ{suf}")
    d010 = _first_col(diq_raw, "DIQ010")
    diq = pd.DataFrame({
        "SEQN": diq_raw["SEQN"],
        "diabetes": np.where(d010 == 1, 1.0, np.where(d010.isin([2, 3]), 0.0, np.nan)),
    })

    df = demo.merge(bmx, on="SEQN", how="left").merge(bp, on="SEQN", how="left")
    df = df.merge(hdl, on="SEQN", how="left").merge(tc_df, on="SEQN", how="left")
    df = df.merge(glu, on="SEQN", how="left").merge(a1c, on="SEQN", how="left")
    df = df.merge(smq, on="SEQN", how="left").merge(diq, on="SEQN", how="left")
    df = df.merge(_mortality(year), on="SEQN", how="left")
    df["cycle"] = year
    return df


# What each sample definition requires, the survey weight that describes it,
# and where the cohort lands. The requirement list is the whole story: every
# measurement a cohort insists on is people it throws away, and since the
# binding constraint on every conclusion here is the number of *events*, asking
# for less data can be worth more than asking for better data.
SAMPLES = {
    "fasting": {
        "requires": ["age", "glucose", "systolic_bp", "bmi", "hdl"],
        "weight": "fasting_weight",
        "file": "cohort.parquet",
        "note": "NHANES morning subsample - fasting glucose needs an 8-hour fast",
    },
    "full": {
        "requires": ["age", "hba1c", "systolic_bp", "bmi", "hdl"],
        "weight": "exam_weight",
        "file": "cohort_full.parquet",
        "note": "whole examined sample - HbA1c needs no fast",
    },
    # No laboratory at all: a blood-pressure cuff, a scale, a height rule and
    # two questions. This is the cohort that matters for reach - a model that
    # needs a venous sample cannot be used where there is no laboratory, which
    # is most of where cardiovascular screening is actually needed.
    "clinical": {
        # BMI is carried in the file but NOT required, because the shipped
        # clinical model does not use it (see train_nhanes.CLINICAL_FEATURES).
        # Insisting on a measurement no model reads would discard 280 people
        # and 52 real events for nothing.
        "requires": ["age", "systolic_bp", "current_smoker"],
        "weight": "exam_weight",
        "file": "cohort_clinical.parquet",
        "note": "no laboratory result required",
    },
}


def main(drop_competing: bool = False, sample: str = "fasting") -> pd.DataFrame:
    spec = SAMPLES[sample]
    required, weight_col, out_name = spec["requires"], spec["weight"], spec["file"]
    frames = [build_cycle(*c) for c in CYCLES]
    df = pd.concat(frames, ignore_index=True)
    # SEQN is only unique within a cycle.
    df["uid"] = df["cycle"].astype(int).astype(str) + "-" + df["SEQN"].astype(int).astype(str)
    n0 = len(df)

    steps = [("all NHANES participants, 6 cycles", n0)]

    df = df.rename(columns={"RIDAGEYR": "age", "BMXBMI": "bmi",
                            "WTMEC2YR": "exam_weight"})
    if "exam_weight" not in df.columns:
        df["exam_weight"] = np.nan
    df = df[(df.age >= 40) & (df.age <= 79)]
    steps.append(("aged 40-79 at examination", len(df)))

    if "RIDEXPRG" in df.columns:
        df = df[df.RIDEXPRG != 1]
        steps.append(("not pregnant at examination", len(df)))

    df = df[df.ELIGSTAT == 1]
    steps.append(("eligible for mortality linkage", len(df)))

    # Void the impossible values rather than dropping the people who have them.
    # An implausible HDL says nothing about that participant's blood pressure,
    # so removing them from a model that never reads HDL would be throwing away
    # a real observation for an unrelated reason. Voiding lets the required-
    # feature filter below remove exactly the people whose *required* inputs are
    # unusable, and nobody else.
    voided = {}
    for col, (lo, hi) in PLAUSIBLE.items():
        if col not in df.columns:
            continue
        bad = df[col].notna() & ((df[col] < lo) | (df[col] > hi))
        if bad.any():
            voided[col] = int(bad.sum())
            df.loc[bad, col] = np.nan
    detail = ", ".join(f"{k} {v}" for k, v in sorted(voided.items())) or "none"
    print(f"  voided physiologically impossible values: {detail}")

    feats = list(required)
    df = df.dropna(subset=feats)
    steps.append((", ".join(feats) + " all measured", len(df)))

    df["died"] = df.MORTSTAT == 1
    df["cvd_death"] = df.died & df.UCOD_LEADING.isin(CVD_CAUSES)
    df["months"] = df.PERMTH_EXM

    df = df.dropna(subset=["months"])
    steps.append(("follow-up time recorded", len(df)))

    # Observed long enough to know the 10-year answer?
    observed = df.died | (df.months >= HORIZON_MONTHS)
    df = df[observed]
    steps.append((f"observed to {HORIZON_MONTHS} months or died", len(df)))

    df["y"] = (df.cvd_death & (df.months <= HORIZON_MONTHS)).astype(int)

    if drop_competing:
        competing = df.died & ~df.cvd_death & (df.months <= HORIZON_MONTHS)
        df = df[~competing]
        steps.append(("excluding competing non-CVD deaths", len(df)))

    print("=== cohort derivation ===")
    prev = None
    for label, n in steps:
        delta = "" if prev is None else f"  (-{prev - n:,})"
        print(f"  {n:>7,}  {label}{delta}")
        prev = n

    df["sex"] = np.where(df.RIAGENDR == 1, "Male", "Female")
    keep = ["age", "glucose", "hba1c", "systolic_bp", "bmi", "hdl",
            "total_cholesterol", "ever_smoker", "current_smoker", "diabetes",
            "y", "sex", "RIDRETH1", "cycle", "months", "died", "cvd_death",
            "fasting_weight", "exam_weight", "uid"]
    out = df[keep].reset_index(drop=True)

    print("\n=== outcome ===")
    print(f"  10-year CVD deaths : {int(out.y.sum()):,}")
    print(f"  event rate         : {out.y.mean():.4f}  ({out.y.mean()*100:.2f}%)")
    print(f"  any death in window: {int((out.died & (out.months<=120)).sum()):,}")
    print("\n=== by cycle ===")
    print(out.groupby('cycle').agg(n=('y','size'), events=('y','sum'),
                                   rate=('y','mean')).to_string())
    print("\n=== by sex ===")
    print(out.groupby('sex').agg(n=('y','size'), events=('y','sum'),
                                 rate=('y','mean')).to_string())
    print("\n=== feature summary ===")
    print(out[feats].describe().T.to_string())

    dest = OUT.parent / out_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(dest, index=False)
    print(f"\nsample={sample}  ({spec['note']})  weight={weight_col}")
    print(f"wrote {dest}  ({len(out):,} rows)")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop-competing", action="store_true")
    ap.add_argument("--sample", choices=sorted(SAMPLES), default="fasting",
                    help="fasting = morning subsample with fasting glucose; "
                         "full = whole examined sample with HbA1c (about 2x larger)")
    main(**vars(ap.parse_args()))
