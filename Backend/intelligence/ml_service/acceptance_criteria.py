"""Acceptance criteria a model must meet before it may serve patients.

**This file is the pre-registration.** It states the thresholds, and the
reasoning behind each one, separately from the code that measures them and
before any particular model is judged. Criteria written after seeing a result
are not criteria, they are a description of that result.

An honest disclosure about version 1: the coverage and abstention thresholds
below were written *after* the first coverage numbers for cvd-nhanes-logreg
3.0.0 were computed, because until that analysis existed nobody knew coverage
was a question at all. They are justified on clinical grounds rather than
fitted to let 3.0.0 pass - and in fact 3.0.0 fails two of them. Every model
from here on is judged against this file as it stood before the run.

Each criterion carries a ``basis``: the clinical reason for the number. A
threshold nobody can justify is a threshold that will be quietly moved the
first time it fails.
"""
from __future__ import annotations

from dataclasses import dataclass

CRITERIA_VERSION = "cvd-acceptance-1"

#: 10-year risk of cardiovascular death at which the intended action - refer
#: for clinician review and intensified prevention - is considered worthwhile.
#:
#: This is deliberately lower than the familiar 7.5% ASCVD figure, because this
#: model predicts cardiovascular *death*, not cardiovascular *events*, and
#: death is the rarer outcome. It is a placeholder that a responsible clinician
#: must replace with a threshold they will actually act on; it is recorded here
#: so that the number being assumed is visible rather than implicit.
DECISION_THRESHOLD = 0.05


@dataclass(frozen=True)
class Criterion:
    key: str
    statement: str
    basis: str


CRITERIA: list[Criterion] = [
    # -- coverage: can the system serve the people it is meant to serve? ----
    Criterion(
        "coverage.overall",
        "At least 90% of the target population can be scored at all.",
        "A screening tool that abstains on a large share of the people it is "
        "pointed at is not a screening tool. Below this level the abstentions, "
        "not the predictions, are the system's main output.",
    ),
    Criterion(
        "coverage.refused_risk_ratio",
        "The event rate among refused patients is no more than 1.5x the event "
        "rate among served patients.",
        "Refusal is itself a clinical act. If the people the system turns away "
        "are markedly sicker than the people it serves, then it is silent "
        "precisely where it is most needed, and its reported performance "
        "describes an easier population than the real one.",
    ),
    Criterion(
        "coverage.group_disparity",
        "No demographic group is refused at more than 1.5x the rate of the "
        "best-served group.",
        "Unequal coverage is unequal care. A group that is disproportionately "
        "refused receives less of whatever benefit the tool provides, and that "
        "gap does not appear anywhere in an accuracy metric.",
    ),
    Criterion(
        "coverage.no_silent_dangerous_refusal",
        "A refusal caused by a required value lying beyond the validated range "
        "on the higher-risk side must say so specifically.",
        "Refusing to score a very high blood pressure with the same words used "
        "for an unusual but harmless value hides the one fact in the record "
        "that most needed attention. The tool may not estimate, but it must "
        "not be silent.",
    ),

    # -- discrimination ------------------------------------------------------
    Criterion(
        "discrimination.above_chance",
        "The lower bound of the overall ROC-AUC confidence interval exceeds 0.5.",
        "Anything that cannot be distinguished from a coin toss must not be "
        "shown to a clinician as evidence.",
    ),
    Criterion(
        "discrimination.beats_age",
        "The model beats age alone, with a paired-bootstrap confidence interval "
        "that excludes zero.",
        "Most of the apparent skill in any cardiovascular risk score is age. A "
        "model that cannot be shown to add anything to the patient's date of "
        "birth is asking clinicians to collect data for no gain.",
    ),
    Criterion(
        "discrimination.subgroup_above_chance",
        "In every subgroup with at least 30 events, the lower bound of the "
        "ROC-AUC confidence interval exceeds 0.5.",
        "Average performance can hide a subgroup where the model is useless. A "
        "clinician seeing one patient is always inside a subgroup, never in "
        "the average.",
    ),

    # -- calibration ---------------------------------------------------------
    Criterion(
        "calibration.slope",
        "The overall calibration slope lies between 0.80 and 1.25.",
        "The output is shown to people as a probability, so it has to be one. "
        "A slope far from 1 means the spread of the predictions is wrong even "
        "when their ranking is right.",
    ),
    Criterion(
        "calibration.subgroup_error",
        "In every subgroup with at least 30 events, predicted risk is within "
        "25% (relative) of observed risk.",
        "A well-calibrated average can contain a group whose risk is "
        "systematically understated. Understatement is the dangerous "
        "direction: it is falsely reassuring.",
    ),

    # -- clinical utility ----------------------------------------------------
    Criterion(
        "utility.beats_default_strategies",
        "At the stated decision threshold, net benefit exceeds both treating "
        "everyone and treating nobody.",
        "Discrimination and calibration describe the number. Net benefit "
        "describes whether acting on it beats the two strategies that need no "
        "model at all, which is the only comparison that justifies deploying "
        "one.",
    ),
]

CRITERIA_BY_KEY = {c.key: c for c in CRITERIA}

# Numeric thresholds, kept beside the statements they belong to.
MIN_COVERAGE = 0.90
MAX_REFUSED_RISK_RATIO = 1.5
MAX_GROUP_REFUSAL_RATIO = 1.5
MIN_SUBGROUP_EVENTS = 30
CALIBRATION_SLOPE_RANGE = (0.80, 1.25)
MAX_SUBGROUP_RELATIVE_ERROR = 0.25
