"""Input checks shared by every path that writes a patient's identity."""
from __future__ import annotations

import datetime as dt

from django.utils import timezone
from rest_framework import serializers

# Older than any documented human lifespan; anything earlier is a typing slip.
OLDEST_PLAUSIBLE_AGE_YEARS = 130


def validate_date_of_birth(value: dt.date | None) -> dt.date | None:
    """Refuse a birth date in the future or beyond a human lifespan.

    Age is derived from this date and passed to the AI analysis, so an
    impossible one is rejected here rather than stored and silently used.
    """
    if value is None:
        return value
    today = timezone.localdate()
    if value > today:
        raise serializers.ValidationError("Date of birth cannot be in the future.")
    if today.year - value.year > OLDEST_PLAUSIBLE_AGE_YEARS:
        raise serializers.ValidationError("Please check the year of birth.")
    return value
