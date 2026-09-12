"""What the detectors actually do on annotated reports.

Four things are counted per detector code, and keeping them apart is the whole
design:

**Agreement.** True and false positives and negatives, from which precision,
recall and F1 follow. Every proportion carries a Wilson score interval,
because a recall of 1.0 from four positive cases is not a recall of 1.0 and
reporting it as one is how a detector gets trusted on nothing.

**Abstention.** How often the detector said ``INSUFFICIENT``. An abstention on
a report the clinician called PRESENT is a miss and is counted as one - a
system that abstained on everything would score a recall of zero, which is
correct. But abstentions are also reported on their own, because a detector
that misses by abstaining and one that misses by saying ABSENT are different
detectors and the second is more dangerous.

**Appropriate abstention.** Where the *clinician* answered
``CANNOT_DETERMINE``, the report genuinely did not settle it. Those items are
excluded from precision and recall, and counted separately along with how
often the system also abstained. That number is the one that says whether the
system knows what it does not know.

**Out-of-scope assertions.** A detector firing on a report where no annotator
thought the code applied. This is never a scoring category; it is a defect
report. Either the annotation schema is incomplete or the detector is firing
somewhere it has no business, and both need a person.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from intelligence.benchmark.reasoning.labels import (
    LabelSource,
    condition_label,
    disagreements,
    finding_label,
)
from intelligence.benchmark.reasoning.schema import (
    ConditionSupport,
    Corpus,
    Determination,
)
from intelligence.benchmark.statistics import (
    CONFIDENCE_LEVEL,
    wilson_interval,
)
from intelligence.findings.contracts import Confidence


@dataclass(slots=True)
class CodeScore:
    """Everything measured about one detector code."""

    code: str
    level: int
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0
    #: Of the false negatives, how many were abstentions rather than a
    #: positive assertion of absence.
    missed_by_abstaining: int = 0
    #: The clinician could not determine it either.
    clinician_could_not_determine: int = 0
    #: ...and of those, how often the system also abstained.
    appropriate_abstentions: int = 0
    #: Annotators disagreed and nobody adjudicated.
    unresolved: int = 0
    #: The detector asserted the code on a report no annotator scoped it to.
    out_of_scope_assertions: int = 0
    examples_of_disagreement: list[str] = field(default_factory=list)

    @property
    def positives(self) -> int:
        """Reports the label called PRESENT. The event count that matters."""
        return self.true_positives + self.false_negatives

    @property
    def negatives(self) -> int:
        return self.true_negatives + self.false_positives

    @property
    def scored(self) -> int:
        return self.positives + self.negatives

    @property
    def precision(self) -> float | None:
        asserted = self.true_positives + self.false_positives
        return self.true_positives / asserted if asserted else None

    @property
    def recall(self) -> float | None:
        return self.true_positives / self.positives if self.positives else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)

    @property
    def false_positive_rate(self) -> float | None:
        return self.false_positives / self.negatives if self.negatives else None

    @property
    def false_negative_rate(self) -> float | None:
        return self.false_negatives / self.positives if self.positives else None

    @property
    def abstention_rate(self) -> float | None:
        """How often the detector declined, over everything it was asked."""
        asked = self.scored + self.clinician_could_not_determine
        if not asked:
            return None
        return (self.missed_by_abstaining + self.appropriate_abstentions) / asked

    @property
    def precision_interval(self) -> tuple[float, float] | None:
        return wilson_interval(
            self.true_positives, self.true_positives + self.false_positives
        )

    @property
    def recall_interval(self) -> tuple[float, float] | None:
        return wilson_interval(self.true_positives, self.positives)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "level": self.level,
            "scored": self.scored,
            "positives": self.positives,
            "negatives": self.negatives,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "missed_by_abstaining": self.missed_by_abstaining,
            "precision": self.precision,
            "precision_interval": self.precision_interval,
            "recall": self.recall,
            "recall_interval": self.recall_interval,
            "f1": self.f1,
            "false_positive_rate": self.false_positive_rate,
            "false_negative_rate": self.false_negative_rate,
            "abstention_rate": self.abstention_rate,
            "clinician_could_not_determine": self.clinician_could_not_determine,
            "appropriate_abstentions": self.appropriate_abstentions,
            "unresolved": self.unresolved,
            "out_of_scope_assertions": self.out_of_scope_assertions,
        }


@dataclass(slots=True)
class BenchmarkResult:
    corpus_id: str
    reports: int
    codes: dict[str, CodeScore] = field(default_factory=dict)
    #: Reports where at least one code went unadjudicated.
    reports_with_unresolved_codes: int = 0
    single_annotator_reports: int = 0
    confidence_level: float = CONFIDENCE_LEVEL

    @property
    def unresolved_rate(self) -> float:
        if not self.reports:
            return 0.0
        return self.reports_with_unresolved_codes / self.reports

    def as_dict(self) -> dict:
        return {
            "corpus_id": self.corpus_id,
            "reports": self.reports,
            "confidence_level": self.confidence_level,
            "unresolved_rate": round(self.unresolved_rate, 4),
            "single_annotator_reports": self.single_annotator_reports,
            "codes": {c: s.as_dict() for c, s in sorted(self.codes.items())},
        }


#: What the system said about one report: code -> the confidence it reached,
#: or absent from the mapping if the detector stayed silent.
SystemOutput = dict[str, Confidence]


def score(
    corpus: Corpus,
    outputs: dict[str, SystemOutput],
    *,
    levels: dict[str, int] | None = None,
) -> BenchmarkResult:
    """Compare the detectors' output against the resolved clinician labels.

    ``outputs`` maps report id to what the system produced for that report.
    A code missing from a report's output means the detector stayed silent,
    which is scored as "did not assert" - the same as ABSENT, because that is
    what a reader sees.
    """
    levels = levels or {}
    result = BenchmarkResult(corpus_id=corpus.corpus_id, reports=len(corpus))

    for item in corpus.items:
        produced = outputs.get(item.report_id, {})
        if item.annotator_count < 2:
            result.single_annotator_reports += 1

        unresolved_here = False
        for code in sorted(item.applicable_finding_codes):
            label = finding_label(item, code)
            entry = result.codes.setdefault(
                code, CodeScore(code=code, level=levels.get(code, 2))
            )
            unresolved_here |= _tally_finding(entry, label, produced.get(code))

        for code in sorted(item.applicable_condition_codes):
            label = condition_label(item, code)
            entry = result.codes.setdefault(
                code, CodeScore(code=code, level=levels.get(code, 3))
            )
            unresolved_here |= _tally_condition(entry, label, produced.get(code))

        for code, said in disagreements(item).items():
            entry = result.codes.get(code)
            if entry is not None and len(entry.examples_of_disagreement) < 20:
                entry.examples_of_disagreement.append(
                    f"{item.report_id}: {', '.join(said)}"
                )

        # A detector firing where nobody scoped it is a defect, not a score.
        scoped = item.applicable_finding_codes | item.applicable_condition_codes
        for code, confidence in produced.items():
            if code not in scoped and confidence is not Confidence.INSUFFICIENT:
                entry = result.codes.setdefault(
                    code, CodeScore(code=code, level=levels.get(code, 2))
                )
                entry.out_of_scope_assertions += 1

        if unresolved_here:
            result.reports_with_unresolved_codes += 1

    return result


def _tally_finding(entry: CodeScore, label, confidence: Confidence | None) -> bool:
    """Returns True when this code was unresolved on this report."""
    asserted = confidence is not None and confidence is not Confidence.INSUFFICIENT
    abstained = confidence is Confidence.INSUFFICIENT

    if label.source is LabelSource.UNRESOLVED:
        entry.unresolved += 1
        return True
    if label.source is LabelSource.NOT_APPLICABLE:
        return False

    if label.determination is Determination.CANNOT_DETERMINE:
        entry.clinician_could_not_determine += 1
        if abstained or confidence is None:
            entry.appropriate_abstentions += 1
        return False

    if label.determination is Determination.PRESENT:
        if asserted:
            entry.true_positives += 1
        else:
            entry.false_negatives += 1
            if abstained:
                entry.missed_by_abstaining += 1
    else:
        if asserted:
            entry.false_positives += 1
        else:
            entry.true_negatives += 1
    return False


def _tally_condition(entry: CodeScore, label, confidence: Confidence | None) -> bool:
    asserted = confidence is not None and confidence is not Confidence.INSUFFICIENT
    abstained = confidence is Confidence.INSUFFICIENT

    if label.source is LabelSource.UNRESOLVED:
        entry.unresolved += 1
        return True
    if label.source is LabelSource.NOT_APPLICABLE:
        return False

    if label.support is ConditionSupport.INSUFFICIENT:
        # The clinician could not say either. Abstaining here is the right
        # answer, and asserting is not a false positive against a real
        # negative - it is a claim nobody could stand behind.
        entry.clinician_could_not_determine += 1
        if abstained or confidence is None:
            entry.appropriate_abstentions += 1
        return False

    if label.support is ConditionSupport.SUPPORTED:
        if asserted:
            entry.true_positives += 1
        else:
            entry.false_negatives += 1
            if abstained:
                entry.missed_by_abstaining += 1
    else:
        if asserted:
            entry.false_positives += 1
        else:
            entry.true_negatives += 1
    return False
