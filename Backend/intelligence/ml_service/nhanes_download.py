"""Fetch the real NHANES cycles and the NCHS linked mortality files.

Everything here is public-use data published by the US CDC/NCHS. Files are
cached on disk so the pipeline is re-runnable without re-downloading.

NHANES gives the features the cvd model consumes (age, sex, systolic_bp, bmi,
smoking, and a glycaemic marker - fasting glucose or HbA1c); the NCHS
public-use linkage gives a real, dated cardiovascular death outcome. Together
they replace the synthetic generator.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "_data" / "raw"
EXAM_BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/{year}/DataFiles/{name}.xpt"
MORT_BASE = (
    "https://ftp.cdc.gov/pub/HEALTH_STATISTICS/NCHS/datalinkage/"
    "linked_mortality/NHANES_{start}_{end}_MORT_2019_PUBLIC.dat"
)

# (start_year, end_year, suffix, hdl_file, glucose_file, hba1c_file)
#
# ``glucose_file`` is the FASTING morning subsample - roughly half of the
# examined sample, because it requires an 8-hour fast and a morning session.
# ``hba1c_file`` (glycohemoglobin) is measured on the FULL sample and needs no
# fast, so a cohort built on it is about twice the size. That difference is the
# whole reason the full-sample cohort exists: see nhanes_cohort.py.
CYCLES = [
    (1999, 2000, "",   "LAB13",  "LAB10AM", "LAB10"),
    (2001, 2002, "_B", "L13_B",  "L10AM_B", "L10_B"),
    (2003, 2004, "_C", "L13_C",  "L10AM_C", "L10_C"),
    (2005, 2006, "_D", "HDL_D",  "GLU_D",   "GHB_D"),
    (2007, 2008, "_E", "HDL_E",  "GLU_E",   "GHB_E"),
    (2009, 2010, "_F", "HDL_F",  "GLU_F",   "GHB_F"),
]


def fetch(url: str, dest: Path) -> str:
    if dest.exists() and dest.stat().st_size > 0:
        return f"cached  {dest.name} ({dest.stat().st_size:,}b)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # The URL is built from the literal https templates above; nothing here
    # is caller-supplied, so there is no scheme to smuggle.
    req = urllib.request.Request(  # noqa: S310 - fixed https templates only
        url, headers={"User-Agent": "Mozilla/5.0 (research)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
            data = r.read()
    except Exception as exc:                      # noqa: BLE001 - report and continue
        return f"FAILED  {dest.name}: {type(exc).__name__} {exc}"
    dest.write_bytes(data)
    return f"ok      {dest.name} ({len(data):,}b)"


def main() -> None:
    for start, end, suf, hdl, glu, a1c in CYCLES:
        print(f"--- NHANES {start}-{end} ---", flush=True)
        names = [f"DEMO{suf}", f"BMX{suf}", f"BPX{suf}", hdl, glu, a1c,
                 f"SMQ{suf}", f"DIQ{suf}"]
        # Total cholesterol has its own file from the 2005-2006 cycle onward;
        # before that it sits alongside HDL in the lipid file.
        if start >= 2005:
            names.append(f"TCHOL{suf}")
        for name in names:
            url = EXAM_BASE.format(year=start, name=name)
            print("  " + fetch(url, RAW / f"{start}" / f"{name}.xpt"), flush=True)
        print("  " + fetch(MORT_BASE.format(start=start, end=end),
                           RAW / f"{start}" / "mortality.dat"), flush=True)


if __name__ == "__main__":
    sys.exit(main())
