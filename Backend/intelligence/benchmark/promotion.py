"""When a claim may stop calling itself unmeasured.

There are two gates because there are two benchmarks, and the split is the
whole point: a detector can have flawless reasoning and be fed a misread
haemoglobin, or perfect extraction feeding an unsafe rule. One combined score
would hide both, and neither gate is allowed to stand in for the other.

**Extraction readiness** gates whether the *parser* has been measured well
enough for anything downstream of it to be measured at all. A reasoning score
computed on a corpus whose extraction was never checked is a number about two
layers at once.

**Detector promotion** gates whether one detector may move from
``NOT_VALIDATED`` to ``BENCHMARKED``.

The requirements below are written before there is any data to run through
them, and that ordering is the point. A threshold chosen after seeing the
numbers is not a threshold, it is a description.

**BENCHMARKED means measured, not good.** A detector whose measured precision
is poor should be ``BENCHMARKED`` - measured, and known to be poor - not left
at ``NOT_VALIDATED`` as though nobody had looked, which would hide the
measurement. So none of the gates below is a performance floor. They ask
whether the measurement is large enough and clean enough to mean anything.

The one exception is deliberate and sits in the extraction gate: a fabrication
rate above zero blocks it. That is not a performance bar, it is a correctness
one. A parser that persists a number the report does not print is not a
less-accurate parser; it is one whose output nobody can act on, and no amount
of corpus size makes that measurable-and-fine.

Promotion is never automatic. This module produces a recommendation; changing
a detector's ``validation_status`` is an edit to the contract in code, made by
a person who has read the numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from intelligence.benchmark.extraction.scoring import ExtractionResult
from intelligence.benchmark.reasoning.scoring import BenchmarkResult, CodeScore

# --- shared -------------------------------------------------------
#: Every document and report read independently, so one person's habits cannot
#: become the ground truth.
MIN_ANNOTATORS = 2

#: Above this share of unadjudicated disagreements the corpus is not describing
#: the system, it is describing the annotators.
MAX_UNRESOLVED_RATE = 0.05

# --- the extraction gate ------------------------------------------
MIN_EXTRACTION_DOCUMENTS = 200

#: Lines that must yield nothing - page numbers, accession numbers, censored
#: results. A corpus without them cannot measure whether the parser invents
#: values, which is the failure that matters most.
MIN_REFUSABLE_LINES = 100

#: Not a performance bar. A parser that persists a value the report does not
#: print produces output nobody can act on.
MAX_FABRICATIONS = 0

#: Below this the detection measurement is too thin to support the word.
MIN_EXTRACTED_FIELDS = 500

# --- the detector gate --------------------------------------------
MIN_CORPUS_REPORTS = 200

#: Recall is estimated only from reports the label called PRESENT, so this is
#: the number that decides whether recall means anything. Thirty gives a Wilson
#: interval around a recall of 0.8 of roughly +/- 0.14 - wide, and honestly so.
MIN_POSITIVE_EVENTS = 30

#: Precision needs the detector to have had a real chance to be wrong.
MIN_NEGATIVE_EVENTS = 30

#: A recall interval wider than this does not support the word "measured".
MAX_RECALL_INTERVAL_WIDTH = 0.35

#: A detector firing where no annotator scoped the code means the measurement
#: did not cover what the detector actually does.
MAX_OUT_OF_SCOPE_ASSERTIONS = 0


@dataclass(frozen=True, slots=True)
class Requirement:
    key: str
    met: bool
    detail: str


@dataclass(slots=True)
class Decision:
    subject: str
    promotable: bool
    requirements: list[Requirement] = field(default_factory=list)
    summary: str = ""

    @property
    def unmet(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.met]

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "promotable": self.promotable,
            "summary": self.summary,
            "unmet": [{"key": r.key, "detail": r.detail} for r in self.unmet],
            "requirements": [
                {"key": r.key, "met": r.met, "detail": r.detail}
                for r in self.requirements
            ],
        }


#: Kept for callers that predate the split.
PromotionDecision = Decision


def _fmt(value: float | None) -> str:
    return "not estimable" if value is None else f"{value:.3f}"


# --- extraction ----------------------------------------------------
def evaluate_extraction(result: ExtractionResult | None) -> Decision:
    """Has the reading layer been measured well enough to build on?"""
    if result is None or result.documents == 0:
        return Decision(
            subject="extraction",
            promotable=False,
            requirements=[Requirement(
                "corpus_exists", False,
                f"No extraction corpus exists. {MIN_EXTRACTION_DOCUMENTS} "
                f"documents, each transcribed by at least {MIN_ANNOTATORS} "
                f"annotators, are needed before the parser can be measured.",
            )],
            summary="never measured",
        )

    requirements = [
        Requirement(
            "corpus_size",
            result.documents >= MIN_EXTRACTION_DOCUMENTS,
            f"{result.documents} documents, {MIN_EXTRACTION_DOCUMENTS} required",
        ),
        Requirement(
            "fields_measured",
            result.expected >= MIN_EXTRACTED_FIELDS,
            f"{result.expected} result lines transcribed, "
            f"{MIN_EXTRACTED_FIELDS} required",
        ),
        Requirement(
            "refusable_lines",
            result.refusable_lines >= MIN_REFUSABLE_LINES,
            f"{result.refusable_lines} lines marked as yielding nothing, "
            f"{MIN_REFUSABLE_LINES} required - without them the corpus cannot "
            f"measure whether the parser invents values",
        ),
        Requirement(
            "double_read",
            result.single_annotator_documents == 0,
            f"{result.single_annotator_documents} documents were transcribed "
            f"by one annotator; every one needs at least {MIN_ANNOTATORS}",
        ),
        Requirement(
            "disagreements_adjudicated",
            result.unresolved_rate <= MAX_UNRESOLVED_RATE,
            f"{result.unresolved_rate:.1%} of documents carry an unadjudicated "
            f"disagreement, at most {MAX_UNRESOLVED_RATE:.0%} allowed",
        ),
        Requirement(
            "no_fabrications",
            result.fabrications <= MAX_FABRICATIONS,
            f"{result.fabrications} values were persisted that the report does "
            f"not print. This is a correctness bar rather than a performance "
            f"one: such a value cannot be acted on, and no corpus size makes "
            f"it acceptable",
        ),
    ]
    return Decision(
        subject="extraction",
        promotable=all(r.met for r in requirements),
        requirements=requirements,
        summary=(
            f"detection P {_fmt(result.detection_precision)} / "
            f"R {_fmt(result.detection_recall)} / "
            f"F1 {_fmt(result.detection_f1)}; "
            f"{result.fabrications} fabrications "
            f"(rate {_fmt(result.fabrication_rate)}); "
            f"refused {result.correctly_refused} of {result.refusable_lines} "
            f"lines that yield nothing"
        ),
    )


# --- one detector --------------------------------------------------
def _summarise(score: CodeScore) -> str:
    interval = score.recall_interval
    band = "" if interval is None else f" (95% CI {interval[0]:.2f}-{interval[1]:.2f})"
    return (
        f"precision {_fmt(score.precision)}, recall {_fmt(score.recall)}{band}, "
        f"F1 {_fmt(score.f1)}, abstained {_fmt(score.abstention_rate)}; "
        f"{score.false_negatives} missed of {score.positives} present, "
        f"{score.missed_by_abstaining} of those by abstaining"
    )


def evaluate(result: BenchmarkResult, code: str) -> Decision:
    """Whether one detector has been measured well enough to stop saying so."""
    score = result.codes.get(code)
    if score is None:
        return Decision(
            subject=code,
            promotable=False,
            requirements=[Requirement(
                "present_in_corpus", False,
                f"{code} does not appear in {result.corpus_id} at all",
            )],
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
            f"clinician; every report needs at least {MIN_ANNOTATORS}",
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

    return Decision(
        subject=code,
        promotable=all(r.met for r in requirements),
        requirements=requirements,
        summary=_summarise(score),
    )


def evaluate_all(result: BenchmarkResult) -> dict[str, Decision]:
    return {code: evaluate(result, code) for code in sorted(result.codes)}


def readiness(
    reasoning: BenchmarkResult | None = None,
    extraction: ExtractionResult | None = None,
) -> dict:
    """How far off either benchmark is, reported layer by layer.

    Never as one number. A caller has to be able to see which layer is the
    obstacle, because they are fixed by completely different work - one needs
    parser changes, the other needs clinician time.
    """
    extraction_decision = evaluate_extraction(extraction)
    state = {
        "extraction": {
            "corpus": "none" if extraction is None else extraction.corpus_id,
            "documents": 0 if extraction is None else extraction.documents,
            "documents_required": MIN_EXTRACTION_DOCUMENTS,
            "ready": extraction_decision.promotable,
            "summary": extraction_decision.summary,
            "blocking": [r.detail for r in extraction_decision.unmet],
        },
    }

    if reasoning is None or reasoning.reports == 0:
        state["reasoning"] = {
            "corpus": "none",
            "reports": 0,
            "reports_required": MIN_CORPUS_REPORTS,
            "promotable_codes": [],
            "blocking": [
                f"No clinician-annotated corpus exists. {MIN_CORPUS_REPORTS} "
                f"reports, each read by at least {MIN_ANNOTATORS} clinicians, "
                f"are needed before any detector can be measured.",
            ],
        }
        return state

    decisions = evaluate_all(reasoning)
    state["reasoning"] = {
        "corpus": reasoning.corpus_id,
        "reports": reasoning.reports,
        "reports_required": MIN_CORPUS_REPORTS,
        "promotable_codes": [c for c, d in decisions.items() if d.promotable],
        "measured_codes": sorted(reasoning.codes),
        "blocking": sorted({
            requirement.detail
            for decision in decisions.values()
            for requirement in decision.unmet
        }),
    }
    return state
