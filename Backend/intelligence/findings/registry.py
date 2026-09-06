"""Every detector the system knows about, in one place.

Registration is explicit rather than by import-scanning, so adding a detector
is a visible line in a diff. The registry refuses two detectors with the same
code: one finding code means one rule, the same way one model version means one
model.
"""
from __future__ import annotations

from intelligence.findings.contracts import Detector, EvidenceLevel

_DETECTORS: dict[str, Detector] = {}


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


def _register_defaults() -> None:
    from intelligence.disease import hematology as disease_hematology
    from intelligence.findings import hematology, metabolic

    for module in (hematology, metabolic, disease_hematology):
        for detector in module.DETECTORS:
            register(detector)


def all_detectors() -> list[Detector]:
    """Detectors in level order, so level 2 runs before level 3 reads it."""
    return sorted(_DETECTORS.values(), key=lambda d: (d.contract.level, d.contract.code))


def by_level(level: EvidenceLevel) -> list[Detector]:
    return [d for d in all_detectors() if d.contract.level is level]


def get(code: str) -> Detector | None:
    return _DETECTORS.get(code)


def known_codes() -> list[str]:
    return sorted(_DETECTORS)


_register_defaults()
