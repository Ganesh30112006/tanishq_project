"""Turn a model output into something a person can safely read and act on.

The self-service path put a calibrated probability in front of someone with no
clinician to interpret it. ``84/100`` next to a disease name is read as a
verdict, which is precisely the failure this platform is built to avoid, so
the patient-facing presentation is composed here, server-side, from the
model's own governance record rather than written into a template.

Three rules drive everything below.

**Say only what the model card supports.** The horizon, the prediction target
and the interpretation sentence come from ``ModelVersion.intended_use``. Where
the card says a value is unspecified, the copy stays silent instead of
implying a timeframe the model never claimed.

**Do not hand a lay reader a number the card does not stand behind.** A score
is shown to a patient only when the model has an external validation record
*and* this particular input passed the reliability check. Otherwise they get
the qualitative band and a plain statement of what the model has and has not
been validated on. Clinicians, who are the intended audience for the raw
output, always see the number - hiding it from them would break decision
support (spec sections 4, 5, 57, 58).

**Always give a next step.** An elevated estimate with no route to a clinician
is worse than useless; it is alarming and inert. Every band carries a concrete
action, and an elevated one leads to booking a consultation.
"""
from __future__ import annotations

from decimal import Decimal

from apps.common.enums import ReliabilityStatus
from apps.patients.presentation import risk_band
from apps.risk.plain_language import describe_feature, describe_gaps
from apps.risk.safety import ELEVATED_BANDS

# --- what a band is called, and what it does and does not mean -------------
_BANDS: dict[str, dict[str, str]] = {
    "LOW": {
        "label": "Lower than average",
        "headline": "Your results do not show raised risk at the moment.",
        "meaning": (
            "This is worked out only from the results already saved in your "
            "record. It is in the lower range."
        ),
    },
    "MEDIUM": {
        "label": "Moderate",
        "headline": "Your results are in the middle range.",
        "meaning": (
            "This is worked out only from the results already saved in your "
            "record. It is neither low nor high. Please talk to a doctor about it."
        ),
    },
    "HIGH": {
        "label": "Higher than average",
        "headline": "Your results should be shown to a doctor.",
        "meaning": (
            "This is worked out only from the results already saved in your "
            "record. It is in the higher range. That is a reason to see a "
            "doctor. It does not mean you have any illness."
        ),
    },
    "CRITICAL": {
        "label": "Much higher than average",
        "headline": "Please show your results to a doctor soon.",
        "meaning": (
            "This is worked out only from the results already saved in your "
            "record. It is in the highest range this tool reports. That is a "
            "reason to see a doctor soon. It does not mean you have any illness."
        ),
    },
}

_NOT_A_DIAGNOSIS = (
    "This is not a diagnosis and not a test result. It is only an estimate worked "
    "out from the results already saved in your record. It cannot see anything "
    "that is not saved there - how you are feeling, your family history, or "
    "anything a doctor would find on examining you."
)

# --- how much weight the reader should give the estimate -------------------
_EVIDENCE_GRADES: dict[str, dict[str, str]] = {
    "NOT_CLINICALLY_VALIDATED": {
        "label": "Not yet checked on real patients",
        "detail": (
            "This tool has not been checked against what actually happened to "
            "real patients. Please take the result as a reason to talk to a "
            "doctor, not as a measurement of your health."
        ),
    },
    "INTERNALLY_VALIDATED": {
        "label": "Checked only on its own data",
        "detail": (
            "This tool has been checked on the same data it was built from, but "
            "not on a separate group of patients. So we do not know how correct "
            "it is for someone like you."
        ),
    },
    "EXTERNALLY_VALIDATED": {
        "label": "Checked on other patients too",
        "detail": (
            "This tool has been checked on a separate group of patients as well. "
            "It is still only a help to your doctor, and a doctor still has to "
            "explain what it means for you."
        ),
    },
}

# --- reliability of *this* input, in plain words ---------------------------
_RELIABILITY_NOTES: dict[str, str] = {
    ReliabilityStatus.LOW_RELIABILITY: (
        "Your details are close to the edge of the range this tool was built for, "
        "so this estimate is less dependable than usual."
    ),
    ReliabilityStatus.OUT_OF_DOMAIN: (
        "Your details are outside the range this tool was built for. Please do not "
        "rely on this estimate."
    ),
    ReliabilityStatus.REVIEW_REQUIRED: (
        "This estimate has been marked for a doctor to check before anyone uses it."
    ),
}

_UNSPECIFIED_MARKERS = ("unspecified", "unknown", "n/a", "none", "tbd")


def band_label(band: str | None) -> str:
    """The reader-facing name of a risk band, e.g. "Much higher than average".

    Exposed so the patient list and the result card show the same words. A raw
    band code like "CRITICAL" reads as a verdict on the person, which is
    exactly what the wording is chosen to avoid.
    """
    if not band:
        return ""
    return _BANDS.get(band, {}).get("label", "")


def _card(model_version) -> dict:
    return getattr(model_version, "intended_use", None) or {}


def _is_specified(value: object) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and not any(marker in text for marker in _UNSPECIFIED_MARKERS)


def evidence_grade(model_version) -> dict[str, str]:
    """How far this model has been validated, from its governance record.

    Derived rather than declared: a model with no external validation dataset
    cannot be described to a patient as validated, whatever its copy says.
    """
    if model_version is None:
        code = "NOT_CLINICALLY_VALIDATED"
    elif getattr(model_version, "external_validation_dataset_version", ""):
        code = "EXTERNALLY_VALIDATED"
    elif getattr(model_version, "validation_dataset_version", ""):
        code = "INTERNALLY_VALIDATED"
    else:
        code = "NOT_CLINICALLY_VALIDATED"
    return {"code": code, **_EVIDENCE_GRADES[code]}


def viewer_sees_raw_output(user) -> bool:
    """Whether this viewer is the intended audience for the model's raw output.

    A clinician reviewing decision support is; anyone else gets the governed
    presentation. Defined once so the result card, the timeline and anything
    added later cannot disagree about it - a figure suppressed in one place and
    restated in another is no protection at all.
    """
    from apps.accounts.permissions import (
        RISK_READ_ASSIGNED,
        RISK_REVIEW,
        PermissionResolver,
    )

    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return PermissionResolver.has_any(user, RISK_REVIEW, RISK_READ_ASSIGNED)


def next_steps(band: str, *, has_gaps: bool) -> list[dict[str, str]]:
    """The concrete actions available to the reader of this result."""
    steps: list[dict[str, str]] = []
    if band in ELEVATED_BANDS:
        steps.append(
            {
                "action": "BOOK_APPOINTMENT",
                "label": "Book a consultation",
                "detail": (
                    "Show this estimate and your recent reports to a doctor. Only a "
                    "doctor can tell you what it means for you. This tool cannot."
                ),
            }
        )
    elif band == "MEDIUM":
        steps.append(
            {
                "action": "BOOK_APPOINTMENT",
                "label": "Book a consultation",
                "detail": "Please mention this to a doctor at your next visit.",
            }
        )
    else:
        steps.append(
            {
                "action": "KEEP_MONITORING",
                "label": "Keep your record up to date",
                "detail": (
                    "This estimate uses only the results already saved in your "
                    "record. Add new reports as you get them, so it stays useful."
                ),
            }
        )
    if has_gaps:
        steps.append(
            {
                "action": "ADD_RESULTS",
                "label": "Add the missing results",
                "detail": "Some of the details this tool needed were not in your record.",
            }
        )
    steps.append(
        {
            "action": "DISCUSS_SYMPTOMS",
            "label": "How you feel is not part of this estimate",
            "detail": (
                "If something feels wrong, tell a doctor, whatever this estimate "
                "shows. This tool was never told how you are feeling."
            ),
        }
    )
    return steps


def interpret(assessment, *, for_clinician: bool = False) -> dict | None:
    """Compose the patient-facing reading of a completed assessment.

    Returns ``None`` for anything that is not a produced score - a blocked
    outcome has nothing to interpret and is described by its gaps instead.
    """
    if assessment.status != assessment.Status.COMPLETED:
        return None
    score: Decimal | None = assessment.calibrated_score
    if score is None:
        return None

    band = risk_band(score)
    copy = _BANDS.get(band, _BANDS["MEDIUM"])
    model_version = getattr(assessment, "model_version", None)
    grade = evidence_grade(model_version)
    reliability = assessment.reliability_status or ""

    # A lay reader gets a number only when the model has been checked against a
    # population it was not built on, and this input was in-domain. Otherwise
    # the figure carries a precision the governance record does not support.
    trustworthy_number = (
        grade["code"] == "EXTERNALLY_VALIDATED" and reliability == ReliabilityStatus.VALID
    )
    show_score = bool(for_clinician or trustworthy_number)

    card = _card(model_version)
    horizon = card.get("prediction_horizon", "")
    target = card.get("prediction_target", "") or getattr(model_version, "prediction_target", "")

    return {
        "band": band,
        "band_label": copy["label"],
        "headline": copy["headline"],
        "what_it_means": copy["meaning"],
        "what_it_does_not_mean": _NOT_A_DIAGNOSIS,
        # Empty where the model card does not commit to one - better silence
        # than an implied timeframe the model never claimed.
        "horizon": str(horizon) if _is_specified(horizon) else "",
        "prediction_target": str(target) if _is_specified(target) else "",
        "show_score": show_score,
        "score_percent": round(float(score) * 100) if show_score else None,
        "score_withheld_reason": (
            ""
            if show_score
            else (
                "We are not showing an exact number here. This tool has not been "
                "checked on a separate group of patients, so an exact number would "
                "look far more certain than it really is. The range above is all "
                "it can honestly tell you."
            )
        ),
        "evidence_grade": grade,
        "reliability_note": _RELIABILITY_NOTES.get(reliability, ""),
        "next_steps": next_steps(band, has_gaps=bool(assessment.missing_features)),
    }


# --- blocked outcomes ------------------------------------------------------
# A block is a *successful* refusal, but only if the reader is told what it
# means and what would change it. "INSUFFICIENT_DATA" on its own reads as a
# malfunction.
_BLOCK_COPY: dict[str, dict[str, str]] = {
    "INSUFFICIENT_DATA": {
        "headline": "There is not enough in your record to give you a reliable estimate.",
        "detail": (
            "Some of the details this tool needs are missing, so it did not guess. "
            "A wrong number here could mislead you."
        ),
    },
    "DATA_OUTDATED": {
        "headline": "Some of your results are too old to use.",
        "detail": (
            "This tool uses only results that are recent enough to still describe "
            "you. Newer results for the items below will let it run."
        ),
    },
    "OUT_OF_DOMAIN": {
        "headline": "This tool was not built for a record like yours.",
        "detail": (
            "Your details are outside the range this tool was tested on, so any "
            "estimate would be unreliable. Please see a doctor, who can examine "
            "you properly. This tool cannot."
        ),
    },
    "REVIEW_REQUIRED": {
        "headline": "A doctor has to look at your record first.",
        "detail": (
            "Something in your saved results needs to be checked before an "
            "estimate would mean anything."
        ),
    },
    "MODEL_UNAVAILABLE": {
        "headline": "This analysis is not available right now.",
        "detail": (
            "No approved tool is switched on for this analysis. There is nothing "
            "wrong with your record."
        ),
    },
}

_BLOCK_FALLBACK = {
    "headline": "The analysis did not give a result.",
    "detail": (
        "The system stopped instead of giving an estimate it could not stand "
        "behind. Nothing has been added to your health record."
    ),
}


def _dangerous_breach(assessment):
    """The first out-of-range reading that sits on the higher-risk side, if any."""
    for breach in getattr(assessment, "domain_breaches", None) or []:
        if breach.get("higher_risk_side"):
            return breach
    return None


def describe_block(assessment) -> dict | None:
    """Explain a blocked outcome, and what would unblock it."""
    if assessment.status != assessment.Status.BLOCKED:
        return None
    code = assessment.outcome_code or ""
    copy = _BLOCK_COPY.get(code, _BLOCK_FALLBACK)
    gaps = describe_gaps(assessment.missing_features)

    # A reading beyond the validated range on the higher-risk side gets its own
    # wording. The generic out-of-domain message - "this tool was not built for
    # a record like yours" - is true but reads as a shrug, and the people it is
    # shown to are the ones whose record contains the most alarming number in
    # it. Nothing here estimates a risk, names a condition, or invents a value:
    # it repeats the reading that is already saved and says to show it to a
    # doctor.
    breach = _dangerous_breach(assessment)
    if breach is not None:
        label = describe_feature(breach["feature"])["label"]
        copy = {
            "headline": "This reading is higher than the tool can check.",
            "detail": (
                f"Your record has {label} saved as {breach['value']:g}. That is "
                f"above the range this tool was tested on, so it has not given "
                f"an estimate - any number would be unreliable. Please show "
                f"this reading to a doctor."
            ),
        }

    return {
        "outcome": code,
        "headline": copy["headline"],
        "detail": copy["detail"],
        "data_needed": gaps,
        # Out-of-domain is not a gap a person can fill by uploading anything.
        "resolvable_by_patient": bool(gaps) and code != "OUT_OF_DOMAIN",
        "reading_needs_review": breach is not None,
    }
