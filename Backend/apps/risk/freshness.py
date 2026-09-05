"""Has anything the model reads changed since an assessment was produced?

Two things depend on this answer, and they are two halves of one idea:

* A result shown on screen is a statement about the record *as it was*. If new
  results have landed since, the number on screen is stale and saying so is a
  safety matter - a person should not act on a figure computed before their
  latest test.
* The self-service cooldown exists because re-running the model on unchanged
  inputs cannot produce a different answer. Once the inputs *have* changed
  that reasoning no longer holds, so the cooldown is waived rather than
  making someone wait out a timer to see the effect of a result they just
  uploaded.

Only sources the feature assembler actually reads count here - laboratory
results and health measurements - and only in a trustworthy clinical state.
An uploaded report that has not yet been extracted and validated changes no
feature, so it must not claim to.
"""
from __future__ import annotations

import datetime as dt

from apps.common.enums import TRUSTWORTHY_CLINICAL_STATES


def has_new_clinical_input_since(patient, moment: dt.datetime | None) -> bool:
    """True when a model-readable value was recorded after ``moment``."""
    if moment is None:
        return False

    from apps.health.models import HealthMeasurement
    from apps.laboratories.models import LabResult

    if HealthMeasurement.objects.filter(
        patient=patient,
        state__in=TRUSTWORTHY_CLINICAL_STATES,
        recorded_at__gt=moment,
    ).exists():
        return True

    return LabResult.objects.filter(
        order__patient=patient,
        state__in=TRUSTWORTHY_CLINICAL_STATES,
        superseded_by__isnull=True,
        recorded_at__gt=moment,
    ).exists()
