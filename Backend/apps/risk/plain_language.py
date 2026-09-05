"""Patient-facing vocabulary for model features (spec sections 22, 51, 58).

A blocked assessment reports its gaps as *feature names* - ``hba1c``,
``systolic_bp`` - because that is what the feature schema calls them. Showing
those to a person who has no doctor sitting next to them is a dead end: they
are told something is missing but not what it is or how to supply it.

This module is the one place that translates a feature name into a term a
person recognises plus the concrete action that would fill the gap. It never
invents a clinical value and never guesses a name it does not know - an
unrecognised feature falls back to its own humanised name with no instruction
attached, which is honest rather than misleading.

All wording here is read by patients, so it stays in plain Indian English:
short everyday words, British spellings, and the names people actually use for
these tests.
"""
from __future__ import annotations

from apps.common.display import display_term

#: How a missing feature can be supplied.
SOURCE_LAB = "LAB_REPORT"
SOURCE_MEASUREMENT = "MEASUREMENT"
SOURCE_PROFILE = "PROFILE"

_HOW: dict[str, str] = {
    SOURCE_LAB: "Upload a lab report that has this test, or ask your lab to send the result.",
    SOURCE_MEASUREMENT: "Add this reading to your record, or get it checked at a consultation.",
    SOURCE_PROFILE: "Fill in this detail in your profile.",
}

#: feature name -> (term a person recognises, where it comes from)
_TERMS: dict[str, tuple[str, str]] = {
    "age": ("Your date of birth", SOURCE_PROFILE),
    "is_male": ("Sex recorded in your profile", SOURCE_PROFILE),
    # Laboratory analytes
    "glucose": ("Blood sugar (glucose)", SOURCE_LAB),
    "fasting_glucose": ("Fasting blood sugar", SOURCE_LAB),
    "hba1c": ("HbA1c (your average blood sugar over the last 3 months)", SOURCE_LAB),
    "total_cholesterol": ("Total cholesterol", SOURCE_LAB),
    "hdl": ("HDL (the good cholesterol)", SOURCE_LAB),
    "ldl": ("LDL (the bad cholesterol)", SOURCE_LAB),
    "triglycerides": ("Triglycerides (a type of fat in the blood)", SOURCE_LAB),
    "creatinine": ("Creatinine (a kidney test)", SOURCE_LAB),
    "hemoglobin": ("Haemoglobin", SOURCE_LAB),
    # Vitals / measurements
    "systolic_bp": ("BP - the upper number", SOURCE_MEASUREMENT),
    "diastolic_bp": ("BP - the lower number", SOURCE_MEASUREMENT),
    "heart_rate": ("Heart rate (pulse)", SOURCE_MEASUREMENT),
    "spo2": ("Oxygen level in the blood (SpO2)", SOURCE_MEASUREMENT),
    "respiratory_rate": ("Breathing rate", SOURCE_MEASUREMENT),
    "temperature": ("Body temperature", SOURCE_MEASUREMENT),
    "weight": ("Weight", SOURCE_MEASUREMENT),
    "height": ("Height", SOURCE_MEASUREMENT),
    "bmi": ("BMI (worked out from your height and weight)", SOURCE_MEASUREMENT),
}


def describe_feature(name: str) -> dict[str, str]:
    """Describe one model feature in terms a person can act on."""
    term, source = _TERMS.get(name, ("", ""))
    return {
        "feature": name,
        "label": term or display_term(name),
        "source": source,
        # No instruction is better than a wrong one for a feature we have not
        # been told how to obtain.
        "how_to_supply": _HOW.get(source, ""),
    }


def describe_gaps(feature_names) -> list[dict[str, str]]:
    """Describe the gaps that blocked an assessment, de-duplicated in order."""
    return [describe_feature(str(name)) for name in dict.fromkeys(feature_names or [])]
