"""A deterministic, auditable report classifier.

No model, no training data - a weighted keyword vote whose every input is
visible in the returned ``signals``. It is intended as the first pass: good
enough to route a clean report, and honest enough to abstain when the document
is ambiguous or unfamiliar. A learned classifier can replace this later behind
the same :func:`classify` signature without any caller changing.
"""
from __future__ import annotations

import re

from intelligence.document.contracts import (
    ClassificationResult,
    ClassificationStatus,
    ReportType,
)

#: term -> weight. Distinctive terms (a panel name) count for more than a term
#: that merely co-occurs with the type (a single analyte).
_SIGNALS: dict[ReportType, dict[str, int]] = {
    ReportType.CBC: {
        "complete blood count": 5, "full blood count": 5, "haemogram": 4,
        "hemogram": 4, "differential count": 3, "hemoglobin": 2, "haemoglobin": 2,
        "hematocrit": 2, "platelet": 2, "wbc": 2, "rbc": 2, "mcv": 2, "mch": 1,
        "neutrophil": 1, "lymphocyte": 1,
    },
    ReportType.LIPID_PROFILE: {
        "lipid profile": 5, "lipid panel": 5, "cholesterol": 2, "hdl": 2,
        "ldl": 2, "triglyceride": 2, "vldl": 2, "non-hdl": 2,
    },
    ReportType.HBA1C: {
        "hba1c": 5, "glycated hemoglobin": 5, "glycated haemoglobin": 5,
        "glycosylated hemoglobin": 5, "a1c": 3, "estimated average glucose": 2,
    },
    ReportType.GLUCOSE: {
        "fasting blood sugar": 4, "fasting glucose": 4, "random blood sugar": 4,
        "oral glucose tolerance": 4, "postprandial": 3, "blood glucose": 3,
        "plasma glucose": 3, "fbs": 2, "rbs": 2, "ppbs": 2,
    },
    ReportType.LIVER_FUNCTION: {
        "liver function": 5, "lft": 4, "hepatic panel": 4, "bilirubin": 2,
        "alt": 2, "ast": 2, "sgpt": 2, "sgot": 2, "alkaline phosphatase": 2,
        "albumin": 1, "ggt": 2,
    },
    ReportType.KIDNEY_FUNCTION: {
        "kidney function": 5, "renal function": 5, "rft": 4, "kft": 4,
        "creatinine": 2, "blood urea": 2, "bun": 2, "egfr": 3, "uric acid": 1,
    },
    ReportType.URINALYSIS: {
        "urinalysis": 5, "urine routine": 5, "urine examination": 4,
        "specific gravity": 2, "pus cells": 2, "epithelial cells": 2,
        "microalbumin": 2, "urine culture": 3,
    },
    ReportType.RADIOLOGY: {
        "impression": 2, "x-ray": 3, "radiograph": 3, "ultrasound": 3,
        "ct scan": 4, "mri": 4, "sonography": 3, "chest radiograph": 4,
        "no acute": 1, "contrast": 1,
    },
    ReportType.PATHOLOGY: {
        "histopathology": 5, "biopsy": 4, "cytology": 4, "gross description": 3,
        "microscopy": 2, "specimen received": 3, "fnac": 4, "malignant": 1,
    },
    ReportType.PRESCRIPTION: {
        "rx": 3, "prescription": 5, "tablet": 2, "capsule": 2, "twice daily": 2,
        "once daily": 2, "mg po": 2, "sig:": 3, "dispense": 3, "refill": 2,
    },
    ReportType.DISCHARGE_SUMMARY: {
        "discharge summary": 5, "date of admission": 4, "date of discharge": 4,
        "hospital course": 4, "discharge medications": 4, "follow up": 1,
        "condition on discharge": 4,
    },
    ReportType.CLINICAL_NOTE: {
        "chief complaint": 4, "history of present illness": 4, "assessment and plan": 4,
        "progress note": 4, "physical examination": 2, "soap note": 4,
    },
}

#: A type needs at least this total weight to be considered at all.
_MIN_SCORE = 4
#: And it must beat the runner-up by at least this ratio to be CLASSIFIED
#: outright; otherwise the document goes to review. A first-pass classifier
#: whose job includes abstaining wants the winner to be clearly dominant, not
#: merely ahead - two signals of comparable strength is exactly the "could be
#: either" case a person should see.
_MARGIN = 2.0

_WORD = re.compile(r"[a-z0-9]+")


def classify(text: str) -> ClassificationResult:
    lowered = (text or "").lower()
    if len(_WORD.findall(lowered)) < 5:
        return ClassificationResult(
            report_type=None, confidence=0.0,
            status=ClassificationStatus.REVIEW_REQUIRED,
            detail="too little text to classify",
        )

    scores: dict[ReportType, int] = {}
    for report_type, terms in _SIGNALS.items():
        score = sum(weight * lowered.count(term) for term, weight in terms.items())
        if score:
            scores[report_type] = score

    if not scores:
        return ClassificationResult(
            report_type=None, confidence=0.0,
            status=ClassificationStatus.REVIEW_REQUIRED,
            signals={}, detail="no recognised report-type keywords",
        )

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_type, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    signals = {rt.value: sc for rt, sc in ranked}

    if best_score < _MIN_SCORE or best_score < _MARGIN * max(runner_up, 1):
        return ClassificationResult(
            report_type=None,
            confidence=round(best_score / (best_score + runner_up + _MIN_SCORE), 3),
            status=ClassificationStatus.REVIEW_REQUIRED,
            signals=signals,
            detail=(
                f"top candidate {best_type.value} (score {best_score}) does not "
                f"clear the margin over the next ({runner_up})"
            ),
        )

    confidence = round(best_score / (best_score + runner_up + _MIN_SCORE), 3)
    return ClassificationResult(
        report_type=best_type, confidence=confidence,
        status=ClassificationStatus.CLASSIFIED, signals=signals,
    )
