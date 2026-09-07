"""How much a result has to move before the move means anything.

Every laboratory value wobbles between samples without the patient changing.
Two things drive it: the assay's own imprecision, and the patient's biological
variation from day to day. A creatinine that goes from 88 to 96 umol/L has not
gone up in any sense a clinician would act on, and a system that drew an arrow
between those two numbers would be manufacturing a trend out of noise.

So no trend is reported here without a stated threshold, and the threshold is
per analyte, because the analytes differ enormously. Sodium is held in a very
narrow band and a 4% move is real; ferritin swings by a third between samples
in the same well person.

**These figures are taken from the literature on analytical and biological
variation. They have not been measured on the assays this system's reports
actually come from**, which vary between laboratories. They are deliberately
set on the conservative side - too large rather than too small - because the
failure they prevent (calling noise a trend) is worse than the one they cause
(calling a real small change stable, which the underlying values still show).
"""
from __future__ import annotations

#: Bump when a threshold changes. Trend findings record which version they used.
VARIATION_TABLE_VERSION = "reference-change-1"

#: Used for any analyte not in the table below. Deliberately large: an analyte
#: nobody has thought about gets the benefit of the doubt.
DEFAULT_SIGNIFICANT_FRACTION = 0.25

#: analyte -> the smallest relative change worth calling a change, as a
#: fraction of the earlier value. Roughly a reference change value: the move
#: needed before analytical and biological variation stop being a sufficient
#: explanation.
_SIGNIFICANT_FRACTION: dict[str, float] = {
    # Tightly regulated: small moves are real.
    "sodium": 0.02,
    "chloride": 0.03,
    "calcium": 0.05,
    "potassium": 0.12,
    "bicarbonate": 0.15,
    # Haematology.
    "hemoglobin": 0.08,
    "hematocrit": 0.09,
    "rbc": 0.08,
    "mcv": 0.04,
    "mch": 0.05,
    "mchc": 0.05,
    "rdw": 0.10,
    "platelets": 0.15,
    "wbc": 0.20,
    # Renal.
    "creatinine": 0.10,
    "egfr": 0.12,
    "urea": 0.22,
    "bun": 0.22,
    "urine_albumin_creatinine_ratio": 0.40,
    # Liver: the transaminases swing widely between samples.
    "alt": 0.40,
    "ast": 0.35,
    "alp": 0.15,
    "ggt": 0.25,
    "bilirubin_total": 0.35,
    "bilirubin_direct": 0.40,
    "albumin": 0.06,
    "total_protein": 0.05,
    # Thyroid. TSH is log-distributed and moves a great deal within a day.
    "tsh": 0.45,
    "free_t4": 0.12,
    "free_t3": 0.15,
    # Metabolic.
    "fasting_glucose": 0.12,
    "random_glucose": 0.30,
    "glucose": 0.30,
    "hba1c": 0.05,
    "cholesterol": 0.10,
    "hdl": 0.12,
    "ldl": 0.15,
    "triglycerides": 0.30,
    "ferritin": 0.33,
}

#: Analytes where a trend must always carry an extra warning, because two
#: results can be produced by methods that are not comparable at all and the
#: report does not say which was used.
_INCOMPARABLE_WITHOUT_METHOD: dict[str, str] = {
    "egfr": (
        "eGFR is calculated, and different laboratories use different "
        "equations. Two values from different laboratories may not be "
        "comparable at all, and the reports do not say which equation was used."
    ),
    "free_t4": (
        "Free T4 assays differ enough between laboratories that two values "
        "from different laboratories are not directly comparable."
    ),
    "free_t3": (
        "Free T3 assays differ enough between laboratories that two values "
        "from different laboratories are not directly comparable."
    ),
    "ferritin": (
        "Ferritin rises with inflammation, so a change may reflect an "
        "intervening illness rather than a change in iron stores."
    ),
    "urine_albumin_creatinine_ratio": (
        "The ratio is transiently raised by fever, hard exercise, a urine "
        "infection and menstruation, none of which appear on the report."
    ),
}


def significant_fraction(analyte: str) -> float:
    """The smallest relative change worth calling a change."""
    return _SIGNIFICANT_FRACTION.get(
        (analyte or "").strip().lower(), DEFAULT_SIGNIFICANT_FRACTION
    )


def is_significant(analyte: str, earlier: float, later: float) -> bool:
    """Has the value moved further than ordinary variation explains?"""
    if earlier == 0:
        return later != 0
    return abs(later - earlier) / abs(earlier) >= significant_fraction(analyte)


def method_caveat(analyte: str) -> str:
    """An extra warning this analyte's trends must always carry, if any."""
    return _INCOMPARABLE_WITHOUT_METHOD.get((analyte or "").strip().lower(), "")


def known_analytes() -> list[str]:
    return sorted(_SIGNIFICANT_FRACTION)
