"""Deterministic data-sufficiency engine (spec sections 24, 32).

Given a feature-schema definition and the feature values assembled from the
authorized record, decide whether a model may run. The decision is pure and
rule-based - no model is consulted, nothing is imputed. If essential
information is unavailable the result is not ``SUFFICIENT`` and the caller
must not predict.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.common.enums import TRUSTWORTHY_CLINICAL_STATES, ClinicalDataState, DataSufficiency


@dataclass(slots=True)
class FeatureValue:
    name: str
    value: float | int | Decimal | None
    state: str
    observed_at: dt.datetime | None = None


@dataclass(slots=True)
class SufficiencyReport:
    status: str
    completeness: float
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    conflicting: list[str] = field(default_factory=list)
    out_of_domain: list[str] = field(default_factory=list)
    #: Structured detail for each out-of-domain feature: which bound was
    #: crossed, in which direction, and whether that is the direction the model
    #: associates with higher risk.
    #:
    #: The names alone are not enough. A blood pressure below the validated
    #: floor and one above the ceiling are both "out_of_domain", and in this
    #: cohort the people above the ceiling die of cardiovascular causes at
    #: 16.1% against 4.9% for those the model serves. Telling both groups the
    #: same thing hides, from the second group, the single most alarming number
    #: in their record. The model still must not extrapolate - but the refusal
    #: has to name what it saw.
    domain_breaches: list[dict] = field(default_factory=list)

    @property
    def is_sufficient(self) -> bool:
        return self.status == DataSufficiency.SUFFICIENT

    def outcome_code(self) -> str:
        return {
            DataSufficiency.SUFFICIENT: "SUFFICIENT",
            DataSufficiency.PARTIALLY_SUFFICIENT: "INSUFFICIENT_DATA",
            DataSufficiency.INSUFFICIENT: "INSUFFICIENT_DATA",
            DataSufficiency.OUT_OF_DOMAIN: "OUT_OF_DOMAIN",
            DataSufficiency.REVIEW_REQUIRED: "REVIEW_REQUIRED",
        }[self.status]


class DataSufficiencyEngine:
    #: minimum completeness below which we never call it "partially sufficient"
    PARTIAL_FLOOR = 0.5

    def evaluate(
        self,
        *,
        definition: dict,
        features: dict[str, FeatureValue],
        now: dt.datetime | None = None,
    ) -> SufficiencyReport:
        now = now or timezone.now()
        required = definition.get("required_features", [])
        default_max_age = definition.get("max_data_age_days")
        valid_domain = definition.get("valid_domain", {})
        # Sign of each feature's standardised coefficient, written into the
        # schema at registration. Absent for older schemas, in which case no
        # breach can be called dangerous and the generic wording is used.
        risk_direction = definition.get("risk_direction", {})
        min_completeness = float(definition.get("minimum_completeness", 1.0))

        report = SufficiencyReport(status=DataSufficiency.INSUFFICIENT, completeness=0.0)
        satisfied = 0

        for spec in required:
            name = spec["name"]
            fv = features.get(name)

            if fv is None or fv.value is None or fv.state not in TRUSTWORTHY_CLINICAL_STATES:
                if fv is not None and fv.state == ClinicalDataState.CONFLICTING:
                    report.conflicting.append(name)
                else:
                    report.missing.append(name)
                continue

            numeric = _to_float(fv.value)
            if numeric is None:
                report.invalid.append(name)
                continue

            max_age = spec.get("max_age_days", default_max_age)
            if max_age is not None:
                if fv.observed_at is None or (now - fv.observed_at) > dt.timedelta(days=max_age):
                    report.stale.append(name)
                    continue

            bounds = valid_domain.get(name) or {}
            lo, hi = bounds.get("min"), bounds.get("max")
            below = lo is not None and numeric < lo
            above = hi is not None and numeric > hi
            if below or above:
                report.out_of_domain.append(name)
                side = "above" if above else "below"
                # Positive coefficient means larger values carry more risk, so
                # a breach above the ceiling is the dangerous direction.
                direction = float(risk_direction.get(name, 0.0) or 0.0)
                report.domain_breaches.append({
                    "feature": name,
                    "value": numeric,
                    "min": lo,
                    "max": hi,
                    "side": side,
                    "higher_risk_side": bool(
                        (side == "above" and direction > 0)
                        or (side == "below" and direction < 0)
                    ),
                })
                continue

            report.present.append(name)
            satisfied += 1

        total = len(required) or 1
        report.completeness = round(satisfied / total, 4)

        report.status = self._classify(report, min_completeness)
        return report

    def _classify(self, report: SufficiencyReport, min_completeness: float) -> str:
        if report.conflicting:
            return DataSufficiency.REVIEW_REQUIRED
        if report.out_of_domain:
            return DataSufficiency.OUT_OF_DOMAIN
        if not report.missing and not report.stale and not report.invalid:
            if report.completeness >= min_completeness:
                return DataSufficiency.SUFFICIENT
        if report.completeness >= max(min_completeness * 0.75, self.PARTIAL_FLOOR):
            return DataSufficiency.PARTIALLY_SUFFICIENT
        return DataSufficiency.INSUFFICIENT


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, InvalidOperation):
        return None
