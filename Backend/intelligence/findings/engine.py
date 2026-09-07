"""Run the detectors, lowest level first.

Level ordering is not a nicety. A level-3 detector reads the level-2 findings
that were just produced, so running them in the wrong order would silently give
level 3 an empty evidence set and turn every condition-likelihood result into
"insufficient evidence" - a failure that looks exactly like honest caution.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from intelligence.findings import registry
from intelligence.findings.base import build_finding
from intelligence.findings.contracts import Confidence, EvidenceLevel, Finding
from intelligence.findings.evidence import EvidenceSet


@dataclass(slots=True)
class FindingsReport:
    findings: list[Finding] = field(default_factory=list)
    #: Analytes on the report that could not be used as evidence, because they
    #: failed validation or had no range to compare against.
    unusable_evidence: list[str] = field(default_factory=list)
    detectors_run: int = 0
    range_table_version: str = ""

    @property
    def asserted(self) -> list[Finding]:
        return [f for f in self.findings if f.asserts_anything]

    @property
    def needs_human_review(self) -> bool:
        return any(f.human_review_required for f in self.asserted)

    @property
    def highest_level(self) -> EvidenceLevel | None:
        levels = [f.level for f in self.asserted]
        return max(levels) if levels else None


def detect(evidence: EvidenceSet, *, detectors=None) -> FindingsReport:
    chosen = list(detectors) if detectors is not None else registry.all_detectors()
    chosen.sort(key=lambda d: (d.contract.level, d.contract.code))

    report = FindingsReport(
        unusable_evidence=sorted(set(evidence.unusable)),
        detectors_run=len(chosen),
        range_table_version=evidence.range_table_version,
    )

    for detector in chosen:
        finding = detector.evaluate(evidence)
        if finding is None:
            continue
        finding = _hold_to_its_timeline(detector.contract, finding, evidence)
        report.findings.append(finding)
        # Only a finding that actually asserts something may be built upon. An
        # "insufficient evidence" result is a statement about the report, not a
        # fact about the patient, and a higher level must not treat it as one.
        if finding.confidence is not Confidence.INSUFFICIENT:
            evidence.add_finding(finding)

    report.findings.sort(key=lambda f: (-f.level.value, f.code))
    return report


def _hold_to_its_timeline(contract, finding: Finding, evidence: EvidenceSet) -> Finding:
    """Refuse a conclusion the evidence set has no timeline for.

    A detector is expected to check this itself and usually does. The backstop
    is here anyway, because the failure it prevents - a single abnormal value
    presented as a persistent one - is not visible in the output. A finding
    that says "possible chronic kidney disease" reads identically whether the
    detector checked ninety days of history or forgot to.
    """
    if finding.confidence is Confidence.INSUFFICIENT:
        return finding
    if evidence.supports(contract.temporality):
        return finding

    return build_finding(
        contract,
        confidence=Confidence.INSUFFICIENT,
        evidence_used=finding.evidence_used,
        evidence_missing=[*finding.evidence_missing, contract.temporality_requirement],
        caveats=[
            "This report covers one point in time. "
            + contract.temporality_requirement
        ],
    )
