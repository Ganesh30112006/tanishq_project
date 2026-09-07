"""Every detector the system knows about, in one place.

Registration is explicit rather than by import-scanning, so adding a detector
is a visible line in a diff. The registry refuses two detectors with the same
code: one finding code means one rule, the same way one model version means one
model.

Loading is deferred to the first query rather than done at import time. The
detector modules import machinery from ``intelligence.findings``, so
registering them while this module is still being imported makes the outcome
depend on which package a caller happened to import first - importing
``intelligence.disease.hepatic`` before ``intelligence.findings`` was enough to
raise a circular-import error. Deferring removes the ordering question
entirely.
"""
from __future__ import annotations

from intelligence.findings.contracts import Detector, EvidenceLevel

_DETECTORS: dict[str, Detector] = {}
_LOADED = False


def register(detector: Detector) -> Detector:
    code = detector.contract.code
    existing = _DETECTORS.get(code)
    if existing is not None and existing.contract != detector.contract:
        raise ValueError(
            f"{code} is already registered with a different contract. One "
            f"finding code means one rule - give the new rule a new code, or a "
            f"new version of the same one."
        )
    _DETECTORS[code] = detector
    return detector


def _ensure_loaded() -> None:
    """Register the built-in detectors, once, on first use."""
    global _LOADED
    if _LOADED:
        return
    # Set the flag before importing, so a re-entrant call from inside one of
    # those imports returns instead of recursing.
    _LOADED = True
    _register_defaults()


def _register_defaults() -> None:
    from intelligence.disease import hematology as disease_hematology
    from intelligence.disease import hepatic as disease_hepatic
    from intelligence.disease import renal as disease_renal
    from intelligence.disease import thyroid as disease_thyroid
    from intelligence.findings import (
        electrolytes,
        hematology,
        hepatic,
        metabolic,
        renal,
        thyroid,
    )

    for module in (hematology, metabolic, renal, hepatic, thyroid,
                   electrolytes, disease_hematology, disease_renal,
                   disease_thyroid, disease_hepatic):
        for detector in module.DETECTORS:
            register(detector)


def all_detectors() -> list[Detector]:
    """Detectors in level order, so level 2 runs before level 3 reads it."""
    _ensure_loaded()
    return sorted(_DETECTORS.values(), key=lambda d: (d.contract.level, d.contract.code))


def by_level(level: EvidenceLevel) -> list[Detector]:
    return [d for d in all_detectors() if d.contract.level is level]


def get(code: str) -> Detector | None:
    _ensure_loaded()
    return _DETECTORS.get(code)


def known_codes() -> list[str]:
    _ensure_loaded()
    return sorted(_DETECTORS)
