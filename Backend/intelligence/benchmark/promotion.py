"""When a detector may stop calling itself NOT_VALIDATED.

The requirements below are written before there is any data to run through
them, and that ordering is the point. A threshold chosen after seeing the
numbers is not a threshold, it is a description.

**BENCHMARKED means measured, not good.** That is the whole reading of the
ladder. A detector whose measured precision is poor should be ``BENCHMARKED``
- measured, and known to be poor - not left at ``NOT_VALIDATED`` as though
nobody had looked. Leaving it unvalidated would hide the measurement, which is
the opposite of what the measurement is for. So none of the gates below is a
performance floor. They ask whether the measurement is large enough and clean
enough to mean anything:

* enough reports in the corpus at all;
* enough reports where the label was PRESENT, because recall is estimated from
  those and nothing else;
* enough where it was ABSENT, because precision needs a chance to be wrong;
* every report read by at least two clinicians;
* disagreements adjudicated rather than left open;
* and an interval on recall narrow enough that "measured" is honest.

Whether a benchmarked detector should be *used* is a separate question with a
separate answer: ``CLINICALLY_APPROVED``, which needs a named person and the
Django governance lifecycle, exactly as a risk model does.

Promotion is never automatic. This module produces a recommendation; changing
a detector's ``validation_status`` is an edit to the contract in code, made by
a person who has read the numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from intelligence.benchmark.scoring import BenchmarkResult, CodeScore

#: The corpus must be at least this large before any code in it is promotable.
#: A small set can be unrepresentative in ways no per-code count reveals.
MIN_CORPUS_REPORTS = 200

#: Recall is estimated only from reports the label called PRESENT, so this is
#: the number that decides whether recall means anything. Thirty gives a
#: Wilson interval around a recall of 0.8 of roughly +/- 0.14 - wide, and
#: honestly so.
MIN_POSITIVE_EVENTS = 30

#: Precision needs the detector to have had a real chance to be wrong.
MIN_NEGATIVE_EVENTS = 30

#: Every report read independently, so a single reader's habits cannot become
#: the ground truth.
MIN_ANNOTATORS_PER_REPORT = 2

#: Above this share of unadjudicated disagreements the corpus is not describing
#: the detector, it is describing the annotators.
MAX_UNRESOLVED_RATE = 0.05

#: A recall interval wider than this does not support the word "measured".
MAX_RECALL_INTERVAL_WIDTH = 0.35

#: A detector firing where no annotator scoped the code is a defect. Any at all
#: blocks promotion, because it means the measurement did not cover what the
#: detector actually does.
MAX_OUT_OF_SCOPE_ASSERTIONS = 0


@dataclass(frozen=True, slots=True)
class Requirement:
    key: str
    met: bool
    detail: str


@dataclass(slots=True)
class PromotionDecision:
    code: str
    promotable: bool
    requirements: list[Requirement] = field(default_factory=list)
    #: What the numbers say, for the person who has to decide. Deliberately
    #: separate from `promotable`: the gate is about the size and cleanliness
    #: of the measurement, not about whether the result is flattering.
    summary: str = ""

    @property
    def unmet(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.met]

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "promotable": self.promotable,
            "summary": self.summary,
            "unmet": [{"key": r.key, "detail": r.detail} for r in self.unmet],
            "requirements": [
                {"key": r.key, "met": r.met, "detail": r.detail}
                for r in self.requirements
            ],
        }


def _fmt(value: float | None) -> str:
    return "not estimable" if value is None else f"{value:.3f}"


def _summarise(score: CodeScore) -> str:
    interval = score.recall_interval
    band = "" if interval is None else f" (95% CI {interval[0]:.2f}-{interval[1]:.2f})"
    return (
        f"precision {_fmt(score.precision)}, recall {_fmt(score.recall)}{band}, "
        f"F1 {_fmt(score.f1)}, abstained {_fmt(score.abstention_rate)}; "
        f"{score.false_negatives} missed of {score.positives} present, "
        f"{score.missed_by_abstaining} of those by abstaining"
    )


def evaluate(result: BenchmarkResult, code: str) -> PromotionDecision:
    """Whether one code has been measured well enough to stop saying so."""
    score = result.codes.get(code)
    if score is None:
        return PromotionDecision(
            code=code,
            promotable=False,
            requirements=[
                Requirement(
                    "present_in_corpus", False,
                    f"{code} does not appear in {result.corpus_id} at all",
                )
            ],
            summary="never measured",
        )

    interval = score.recall_interval
    width = None if interval is None else interval[1] - interval[0]

    requirements = [
        Requirement(
            "corpus_size",
            result.reports >= MIN_CORPUS_REPORTS,
            f"{result.reports} reports, {MIN_CORPUS_REPORTS} required",
        ),
        Requirement(
            "positive_events",
            score.positives >= MIN_POSITIVE_EVENTS,
            f"{score.positives} reports labelled present, "
            f"{MIN_POSITIVE_EVENTS} required - recall is estimated from these "
            f"and nothing else",
        ),
        Requirement(
            "negative_events",
            score.negatives >= MIN_NEGATIVE_EVENTS,
            f"{score.negatives} reports labelled absent, "
            f"{MIN_NEGATIVE_EVENTS} required - precision needs a chance to be "
            f"wrong",
        ),
        Requirement(
            "double_read",
            result.single_annotator_reports == 0,
            f"{result.single_annotator_reports} reports were read by one "
            f"clinician; every report needs at least "
            f"{MIN_ANNOTATORS_PER_REPORT}",
        ),
        Requirement(
            "disagreements_adjudicated",
            result.unresolved_rate <= MAX_UNRESOLVED_RATE,
            f"{result.unresolved_rate:.1%} of reports carry an unadjudicated "
            f"disagreement, at most {MAX_UNRESOLVED_RATE:.0%} allowed",
        ),
        Requirement(
            "recall_interval",
            width is not None and width <= MAX_RECALL_INTERVAL_WIDTH,
            "recall interval is not estimable" if width is None
            else f"95% CI on recall spans {width:.2f}, at most "
                 f"{MAX_RECALL_INTERVAL_WIDTH} allowed",
        ),
        Requirement(
            "no_out_of_scope_assertions",
            score.out_of_scope_assertions <= MAX_OUT_OF_SCOPE_ASSERTIONS,
            f"{score.out_of_scope_assertions} assertions on reports where no "
            f"annotator scoped this code - the measurement does not cover what "
            f"the detector does",
        ),
    ]

    return PromotionDecision(
        code=code,
        promotable=all(r.met for r in requirements),
        requirements=requirements,
        summary=_summarise(score),
    )


def evaluate_all(result: BenchmarkResult) -> dict[str, PromotionDecision]:
    return {code: evaluate(result, code) for code in sorted(result.codes)}


def readiness(result: BenchmarkResult | None) -> dict:
    """What still stands between the corpus and any promotion at all.

    Answers the question honestly when there is no corpus, which is the state
    the system is actually in.
    """
    if result is None or result.reports == 0:
        return {
            "corpus": "none",
            "reports": 0,
            "reports_required": MIN_CORPUS_REPORTS,
            "promotable_codes": [],
            "blocking": [
                f"No annotated corpus exists. {MIN_CORPUS_REPORTS} reports, "
                f"each read by at least {MIN_ANNOTATORS_PER_REPORT} clinicians, "
                f"are needed before any detector can be measured.",
            ],
        }

    decisions = evaluate_all(result)
    promotable = [c for c, d in decisions.items() if d.promotable]
    blocking = sorted({
        requirement.detail
        for decision in decisions.values()
        for requirement in decision.unmet
    })
    return {
        "corpus": result.corpus_id,
        "reports": result.reports,
        "reports_required": MIN_CORPUS_REPORTS,
        "promotable_codes": promotable,
        "measured_codes": sorted(result.codes),
        "blocking": blocking,
    }
