"""Safety messaging for results a person may read without a doctor present.

The self-service path removed the doctor who used to stand between the model
and the reader. That person is the one who would have said "this is a
long-term estimate, but if you feel unwell *now*, go and get seen". Nothing in
a calibrated probability says that, so the system has to say it explicitly.

Kept here, server-side, so every client shows the same words: the wording is
a safety control, not presentation, and must not drift between clients. It is
written in plain Indian English, because the person reading it may be
frightened and has no doctor next to them to explain anything.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from apps.patients.presentation import risk_band

#: Bands where a person reading alone needs urgent-symptom guidance attached.
ELEVATED_BANDS = frozenset({"HIGH", "CRITICAL"})


def urgent_care_notice(calibrated_score: Decimal | float | None) -> dict[str, str] | None:
    """Guidance to attach to an elevated result, or ``None``.

    A risk model estimates likelihood over a *period of time*; it says nothing
    about whether someone is in trouble right now. Mixing up the two is the
    obvious failure mode of showing this to the public, so an elevated band
    carries a plain instruction to get help for sudden symptoms whatever the
    score says.
    """
    if calibrated_score is None:
        return None
    if risk_band(calibrated_score) not in ELEVATED_BANDS:
        return None
    return {
        "level": "URGENT_SYMPTOMS",
        "headline": "If you are feeling unwell right now, do not wait.",
        "detail": (
            "This estimate is about your risk over a long period. It cannot tell "
            "you whether something is wrong today. If you have chest pain, sudden "
            "breathlessness, weakness or numbness on one side, trouble speaking, "
            "or you feel this may be an emergency, go to the nearest hospital at "
            "once or call the emergency number."
        ),
        "emergency_number": str(getattr(settings, "EMERGENCY_CONTACT_NUMBER", "")),
    }
