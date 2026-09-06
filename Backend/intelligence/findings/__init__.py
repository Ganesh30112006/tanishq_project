"""Turning validated measurements into named clinical findings.

This is levels 1-3 of the detection framework. Level 1 (a value against its
reference range) already comes out of ``intelligence.document``; this package
adds level 2 (named patterns) and hosts the contract that level 3
(``intelligence.disease``) and level 4 (the governed risk models in Django)
also implement.

The shape of every result is the same regardless of level: which detector and
version produced it, how much evidence stands behind the detector itself, the
traceable evidence used, the evidence that was missing, and an explanation
taken from the approved knowledge dictionary rather than composed on the spot.

    from intelligence.findings import build_evidence, detect

    evidence = build_evidence(result.values, sex="female")
    report = detect(evidence)
"""
from __future__ import annotations

from intelligence.findings.contracts import (
    Confidence,
    Detector,
    DetectorValidation,
    EvidenceContract,
    EvidenceLevel,
    EvidenceRef,
    EvidenceRequirement,
    Finding,
)
from intelligence.findings.engine import FindingsReport, detect
from intelligence.findings.evidence import EvidenceSet, Measurement, build_evidence
from intelligence.findings.registry import all_detectors, get, known_codes, register

__all__ = [
    "EvidenceLevel",
    "DetectorValidation",
    "Confidence",
    "EvidenceRequirement",
    "EvidenceContract",
    "EvidenceRef",
    "Finding",
    "Detector",
    "EvidenceSet",
    "Measurement",
    "build_evidence",
    "detect",
    "FindingsReport",
    "all_detectors",
    "register",
    "get",
    "known_codes",
]
