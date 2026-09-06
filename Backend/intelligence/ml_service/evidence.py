"""The eleven questions every model in this system has to face.

A model is not made trustworthy by a good AUC. It is made trustworthy by a
record that can say where it came from, who it was tested on, who it leaves
out, when it declines to answer, and - the part almost every ML project skips -
**what is still unknown about it**.

This module assembles that record from the artifacts the pipeline already
writes, and answers, for any model version::

    1.  Where was it developed?
    2.  Where was it validated?
    3.  Who was represented?
    4.  Who was excluded?
    5.  How often does it abstain?
    6.  Why does it abstain?
    7.  How well does it discriminate?
    8.  How well calibrated is it?
    9.  Does performance vary by subgroup?
    10. Does performance transport?
    11. What evidence is still missing?

Three design rules make this a governance artifact rather than a summary.

**An unanswered question is an output, not an omission.** Every question gets a
status of ``answered``, ``partial`` or ``unanswered``, and anything short of
``answered`` must carry ``to_answer_this``: the specific data or run that would
close it. A question that quietly disappears because its artifact was missing
is the failure mode this file exists to prevent.

**Question 11 is derived, never written.** It is exactly the set of other
questions that are not fully answered. Nobody can compose a reassuring list of
"known limitations" by hand while the measurements say otherwise, because the
list is computed from the measurements.

**A conclusion needs enough evidence to support it, not just a point
estimate.** Transportability with an interval spanning "works well" and "does
not work" is reported as unanswered, with the interval shown. That is why
:data:`MEANINGFUL_AUC_DROP` exists and is stated up front.

Run it::

    python -m intelligence.ml_service.evidence --version 3.1.0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from intelligence.ml_service import acceptance_criteria as AC

ARTIFACTS = Path(__file__).resolve().parents[1] / "_artifacts"

#: The question set is versioned, because the point of a fixed question set is
#: that a later model cannot be asked easier questions than an earlier one.
QUESTIONS_VERSION = "evidence-questions-1"

ANSWERED = "answered"
PARTIAL = "partial"
UNANSWERED = "unanswered"

#: A drop in discrimination at least this large would change whether the tool
#: is worth using. Transport is treated as *established* only when the external
#: confidence interval rules such a drop out - not when the point estimate
#: happens to look acceptable. Overlapping intervals are a weak test and are
#: never reported as agreement.
MEANINGFUL_AUC_DROP = 0.05

#: Below this many events in a group, an estimate is shown and no conclusion is
#: drawn from it. Kept in step with the external validation harness.
MIN_EVENTS_FOR_A_CONCLUSION = 25


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    why: str


QUESTIONS: tuple[Question, ...] = (
    Question(
        "development_population", "Where was it developed?",
        "Everything a model knows comes from the people it was fitted on. A "
        "reader who does not know who those people were cannot judge anything "
        "else in this record.",
    ),
    Question(
        "validation_populations", "Where was it validated?",
        "Performance measured on the data a model was fitted on is not "
        "evidence. Which populations were held out, and how far each one is "
        "from the development data, sets the ceiling on every claim below.",
    ),
    Question(
        "representation", "Who was represented?",
        "A group that was absent from development is a group the model has no "
        "information about, however good its overall numbers look.",
    ),
    Question(
        "exclusions", "Who was excluded?",
        "Exclusions are usually made for good technical reasons and are "
        "almost never random. The people removed to make a clean dataset are "
        "often the sickest, and the reported performance then describes an "
        "easier population than the real one.",
    ),
    Question(
        "abstention_rate", "How often does it abstain?",
        "Refusal is the system's second output. A tool that declines on a "
        "large share of the people it is pointed at is mostly an abstention "
        "engine, whatever its accuracy on the rest.",
    ),
    Question(
        "abstention_reasons", "Why does it abstain?",
        "A missing measurement and a reading beyond the validated range are "
        "different clinical situations. Treating them alike hides the second, "
        "which is often the most alarming number in the record.",
    ),
    Question(
        "discrimination", "How well does it discriminate?",
        "Whether the model ranks a higher-risk person above a lower-risk one, "
        "and whether it does so better than the simplest available baseline.",
    ),
    Question(
        "calibration", "How well calibrated is it?",
        "A ranking is enough to sort a list; an absolute risk is what a "
        "threshold acts on. A model can rank well and still be wrong about "
        "level, and a decision threshold applied to a miscalibrated risk acts "
        "on the wrong people.",
    ),
    Question(
        "subgroup_variation", "Does performance vary by subgroup?",
        "An average holds while the groups behind it are averaged together. "
        "Care is delivered one patient at a time, in one group at a time.",
    ),
    Question(
        "transportability", "Does performance transport?",
        "The only question that matters for a model developed somewhere other "
        "than where it will be used - and the one most often answered by "
        "assumption.",
    ),
    Question(
        "missing_evidence", "What evidence is still missing?",
        "Derived from the answers above rather than written. A model whose "
        "gaps are stated can be used carefully; a model whose gaps are "
        "unstated is used as though it had none.",
    ),
)

_BY_KEY = {question.key: question for question in QUESTIONS}
DERIVED_KEY = "missing_evidence"


@dataclass
class Answer:
    key: str
    status: str
    answer: str
    evidence: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    to_answer_this: str = ""

    def as_dict(self) -> dict:
        question = _BY_KEY[self.key]
        return {
            "key": self.key,
            "question": question.text,
            "why_it_matters": question.why,
            "status": self.status,
            "answer": self.answer,
            "evidence": self.evidence,
            "sources": self.sources,
            "to_answer_this": self.to_answer_this,
        }


def _unanswered(key: str, because: str, to_answer_this: str) -> Answer:
    return Answer(key, UNANSWERED, because, to_answer_this=to_answer_this)


# --- the individual questions --------------------------------------------
def _development_population(card, clinical, external) -> Answer:
    if not card:
        return _unanswered(
            "development_population",
            "No model card was found, so nothing about this model's origin can "
            "be stated.",
            "Train the model, which writes cvd-<version>.meta.json.",
        )
    metrics = card.get("validation_metrics", {})
    domain = (card.get("population_domain") or {}).get("description", "")
    return Answer(
        "development_population",
        ANSWERED,
        f"{domain} Fitted on {metrics.get('n_train', 0):,} people with "
        f"{metrics.get('events_train', 0):,} events, using the features "
        f"{', '.join(card.get('feature_order', []))}.",
        {
            "dataset_version": card.get("training_dataset_version", ""),
            "description": domain,
            "n_train": metrics.get("n_train"),
            "events_train": metrics.get("events_train"),
            "n_calibration": metrics.get("n_calibration"),
            "features": card.get("feature_order", []),
            "split_design": metrics.get("split_design", ""),
            "leakage_check": metrics.get("leakage_check", ""),
        },
        ["meta"],
    )


def _validation_populations(card, clinical, external) -> Answer:
    populations = []
    if card:
        metrics = card.get("validation_metrics", {})
        populations.append({
            "role": "internal_test",
            "dataset_version": card.get("validation_dataset_version", ""),
            "n": metrics.get("n_test"),
            "events": metrics.get("events_test"),
            "horizon_months": 120,
            "note": metrics.get("split_design", ""),
        })
    if external:
        cohort = external.get("cohort", {})
        discrimination = external.get("discrimination", {})
        populations.append({
            "role": cohort.get("role", "external"),
            "dataset_version": cohort.get("key", external.get("population", "")),
            "n": discrimination.get("n"),
            "events": discrimination.get("events"),
            "horizon_months": external.get("horizon_months"),
            "note": external.get("population", ""),
        })
    if not populations:
        return _unanswered(
            "validation_populations",
            "No validation artifact was found.",
            "Run the training pipeline and the external validation harness.",
        )

    # Being able to name the validation populations is not the same as having
    # validated in the population the tool is for. That gap belongs to the
    # transportability question, but it must be visible here too.
    has_external = any(p["role"] == "external" for p in populations)
    status = ANSWERED if has_external else PARTIAL
    described = "; ".join(
        f"{p['role']} ({p['dataset_version']}, n={p['n']:,}, "
        f"{p['events']:,} events, {p['horizon_months']}-month outcome)"
        for p in populations if p["n"]
    )
    return Answer(
        "validation_populations",
        status,
        f"Validated on: {described}. No prospective validation and no "
        f"validation in a healthcare setting - every population here is a "
        f"survey cohort scored retrospectively.",
        {"populations": populations, "prospective_validation": False,
         "validated_in_a_care_setting": False},
        [s for s in ("meta" if card else None, "external" if external else None) if s],
        to_answer_this="" if status == ANSWERED else
        "Run the external validation harness on a cohort not used in development.",
    )


def _representation(card, clinical, external) -> Answer:
    if not card:
        return _unanswered(
            "representation", "No model card was found.",
            "Train the model.",
        )
    subgroups = (card.get("validation_metrics") or {}).get("subgroup", [])
    development = [
        {"group": row.get("label"), "n": row.get("n"), "events": row.get("events")}
        for row in subgroups
    ]
    labels = " ".join(str(row.get("label", "")) for row in subgroups)

    external_groups = []
    if external:
        external_groups = [
            {"group": row["group"], "n": row["n"], "events": row["events"]}
            for row in external.get("discrimination_by_ethnicity", [])
        ]
    external_labels = " ".join(row["group"] for row in external_groups)

    # The distinction that matters is between a group that was counted and
    # found to be small, and a group the source data had no category for. The
    # second cannot be fixed by weighting or by a larger sample of the same
    # survey - the information was never collected.
    in_development = "asian" in labels.lower()
    in_external = "asian" in external_labels.lower()

    if in_development:
        return Answer(
            "representation", ANSWERED,
            "The development cohort's group breakdown is recorded, including "
            "the group this tool is intended for.",
            {"development": development, "external": external_groups},
            ["meta", "external"] if external else ["meta"],
        )
    return Answer(
        "representation", PARTIAL,
        "The development cohort's group sizes are recorded for every category "
        "the source survey used, but that coding scheme had no South Asian or "
        "Asian category at all, so the number of participants from the "
        "intended population is not merely small - it is unknown and "
        "unrecoverable from this data."
        + (f" The external cohort does record it: "
           f"{[g for g in external_groups if 'Asian' in g['group']]}."
           if in_external else ""),
        {"development": development, "external": external_groups,
         "target_population_counted_in_development": False,
         "target_population_counted_externally": in_external},
        ["meta", "external"] if external else ["meta"],
        to_answer_this=(
            "A cohort from the intended population, where the group is recorded "
            "rather than folded into an 'other' category."
        ),
    )


def _exclusions(card, clinical, external) -> Answer:
    """Both kinds of exclusion, kept apart.

    People leave in two different ways and they are not interchangeable. Some
    were never in the cohort - removed by a construction step when the dataset
    was built. Others are in the target population every day and are refused a
    score at the point of use. A record that reports only the second makes the
    model look as though it were built on everybody.
    """
    criteria = ((card or {}).get("intended_use") or {}).get("exclusion_criteria", [])
    if not criteria:
        return _unanswered(
            "exclusions", "No exclusion criteria are recorded.",
            "Record them in the model card's intended-use block.",
        )

    evidence = {"stated_exclusion_criteria": criteria}
    sources = ["meta"]
    parts = [f"{len(criteria)} exclusion criteria are stated."]

    development = _development_derivation(card)
    if development:
        evidence["development_cohort_derivation"] = development["steps"]
        sources.append("cohort_derivation")
        removed = development["steps"][0]["remaining"] - development["steps"][-1]["remaining"]
        parts.append(
            f"Building the development cohort removed {removed:,} of "
            f"{development['steps'][0]['remaining']:,} people, step by step, "
            f"and each step's effect is recorded."
        )
    else:
        parts.append(
            "For the development cohort only the stated criteria are on record, "
            "not how many people each one removed - the construction ladder was "
            "printed when the cohort was built and not kept."
        )

    if external and external.get("derivation"):
        evidence["external_cohort_derivation"] = external["derivation"]
        sources.append("external")

    if clinical:
        coverage = clinical.get("coverage", {})
        evidence["refused_at_scoring_time"] = {
            "target_population": coverage.get("target_population"),
            "refused": coverage.get("refused"),
            "served_event_rate": coverage.get("served_event_rate"),
            "refused_event_rate": coverage.get("refused_event_rate"),
            "refused_risk_ratio": coverage.get("refused_risk_ratio"),
        }
        sources.append("clinical")
        parts.append(
            f"Separately from construction, {coverage.get('refused', 0):,} of "
            f"{coverage.get('target_population', 0):,} people in the target "
            f"population are refused a score at the point of use, and they die "
            f"at {coverage.get('refused_risk_ratio')}x the rate of those served."
        )

    status = ANSWERED if development else PARTIAL
    return Answer(
        "exclusions", status, " ".join(parts), evidence, sources,
        to_answer_this="" if development else (
            "Rebuild the cohort and retrain. The ladder is now written to "
            "<cohort>.derivation.json at build time, so the next trained "
            "version answers this; it cannot be reconstructed for a version "
            "already fitted."
        ),
    )


def _development_derivation(card):
    """The ladder for the sample this model was actually trained on."""
    sample = ((card or {}).get("validation_metrics") or {}).get("cohort")
    if not sample:
        return None
    from intelligence.ml_service.nhanes_cohort import OUT, SAMPLES

    spec = SAMPLES.get(sample)
    if not spec:
        return None
    path = (OUT.parent / spec["file"]).with_suffix(".derivation.json")
    return _load(path)


def _abstention_rate(card, clinical, external) -> Answer:
    if not clinical:
        return _unanswered(
            "abstention_rate",
            "Coverage has not been measured against a target population.",
            "Run the clinical validation harness.",
        )
    coverage = clinical["coverage"]
    rows = {"development": {
        "target_population": coverage["target_population"],
        "served": coverage["served"],
        "coverage": coverage["coverage"],
        "abstention_rate": round(1 - coverage["coverage"], 4),
    }}
    sources = ["clinical"]
    if external:
        outside = external["coverage"]
        rows["external"] = {
            "target_population": outside["target_population"],
            "served": outside["served"],
            "coverage": outside["coverage"],
            "abstention_rate": round(1 - outside["coverage"], 4),
        }
        sources.append("external")
    described = ", ".join(
        f"{name} {row['abstention_rate']:.1%} ({row['target_population'] - row['served']:,} "
        f"of {row['target_population']:,})"
        for name, row in rows.items()
    )
    return Answer(
        "abstention_rate", ANSWERED,
        f"The system declines to produce an estimate for {described}.",
        rows, sources,
    )


def _abstention_reasons(card, clinical, external) -> Answer:
    if not clinical:
        return _unanswered(
            "abstention_reasons", "Abstention has not been analysed.",
            "Run the clinical validation harness.",
        )
    coverage = clinical["coverage"]
    breaches = coverage.get("domain_breaches", [])
    dangerous = [b for b in breaches if b.get("higher_risk_side")]
    groups = clinical.get("refusal_by_group", {})
    disparity = {}
    for column, rows in groups.items():
        rates = [r["refusal_rate"] for r in rows if r.get("refusal_rate") is not None]
        if rates and min(rates) > 0:
            disparity[column] = round(max(rates) / min(rates), 3)
    return Answer(
        "abstention_reasons", ANSWERED,
        f"{coverage['refused_missing']:,} refusals are caused by an input that "
        f"was never recorded and {coverage['refused_out_of_domain']:,} by a "
        f"value beyond the range the model was fitted on. Of the second kind, "
        f"{sum(b['n'] for b in dangerous):,} lie on the side the model "
        f"associates with higher risk, and those refusals name the reading "
        f"rather than giving a generic decline.",
        {
            "refused_missing": coverage["refused_missing"],
            "refused_out_of_domain": coverage["refused_out_of_domain"],
            "domain_breaches": breaches,
            "refusal_rate_disparity": disparity,
            "refusal_by_group": groups,
        },
        ["clinical"],
    )


def _discrimination(card, clinical, external) -> Answer:
    if not card:
        return _unanswered(
            "discrimination", "No model card was found.", "Train the model.",
        )
    metrics = card["validation_metrics"]
    primary = metrics["primary"]
    baseline = metrics.get("age_only_baseline", {})
    against = metrics.get("vs_age_alone", {})
    evidence = {
        "internal_test": {
            "n": primary["n"], "events": primary["events"],
            "roc_auc": primary["roc_auc"], "roc_auc_ci": primary["roc_auc_ci"],
        },
        "age_only_baseline_roc_auc": baseline.get("roc_auc"),
        "improvement_over_age_alone": against,
    }
    if external:
        evidence["external"] = external.get("discrimination", {})
    return Answer(
        "discrimination", ANSWERED,
        f"ROC-AUC {primary['roc_auc']} (95% CI {primary['roc_auc_ci'][0]}-"
        f"{primary['roc_auc_ci'][1]}) on the internal test set. Age alone "
        f"reaches {baseline.get('roc_auc')}, so the other features add "
        f"{against.get('mean_diff')} (95% CI {against.get('ci', ['?', '?'])[0]} "
        f"to {against.get('ci', ['?', '?'])[1]}). Age remains the dominant input.",
        evidence, ["meta", "external"] if external else ["meta"],
    )


def _calibration(card, clinical, external) -> Answer:
    if not card:
        return _unanswered(
            "calibration", "No model card was found.", "Train the model.",
        )
    primary = card["validation_metrics"]["primary"]
    evidence = {
        "internal_test": {
            "calibration_slope": primary.get("calibration_slope"),
            "calibration_in_the_large": primary.get("calibration_in_the_large"),
            "mean_predicted": primary.get("mean_predicted"),
            "observed": primary.get("observed"),
            "hosmer_lemeshow_p": primary.get("hosmer_lemeshow_p"),
        },
        "external": {"reported": False, "because": "no external report"},
    }
    gap = ("Calibration has never been measured outside the development "
           "survey. ")
    if external:
        evidence["external"] = {
            "reported": external.get("calibration_reported", False),
            "because": external.get("calibration_not_reported_because", ""),
            "ordering_only": external.get("risk_gradient", []),
            "ordering_monotonic": external.get("gradient_monotonic"),
        }
        if evidence["external"]["reported"]:
            return Answer(
                "calibration", ANSWERED,
                "Calibration is measured both internally and on an external "
                "population.",
                evidence, ["meta", "external"],
            )
        gap += external.get("calibration_not_reported_because", "")
    return Answer(
        "calibration", PARTIAL,
        f"Internally the calibration slope is "
        f"{primary.get('calibration_slope')} against an ideal of 1.0, with "
        f"predicted {primary.get('mean_predicted')} against observed "
        f"{primary.get('observed')}. Externally it is not reported. {gap}",
        evidence, ["meta", "external"] if external else ["meta"],
        to_answer_this=(
            "A cohort observed for the model's full prediction horizon. Until "
            "one exists, the absolute risks this model produces are unverified "
            "outside its development survey, and the decision threshold acts "
            "on those absolute risks."
        ),
    )


def _subgroup_variation(card, clinical, external) -> Answer:
    """Subgroup performance, judged on the same rows the criteria use.

    The event floor here is deliberately the acceptance criteria's floor, and
    the relative error is computed the same way. Two places in one system
    measuring "subgroup calibration error" differently is how a dossier ends up
    reporting a 42% error beside a criteria file reporting a pass - and the 42%
    would have come from a group with 21 events, which supports no conclusion
    at all.
    """
    if not card or not card.get("subgroup_metrics"):
        return _unanswered(
            "subgroup_variation", "No subgroup breakdown was found.",
            "Train the model, which writes the subgroup metrics.",
        )
    rows = (card.get("validation_metrics") or {}).get("subgroup", [])
    floor = AC.MIN_SUBGROUP_EVENTS
    conclusive = [r for r in rows if r.get("events", 0) >= floor]
    underpowered = [{"group": r["group"], "n": r["n"], "events": r["events"],
                     "roc_auc": r["roc_auc"], "roc_auc_ci": r.get("roc_auc_ci")}
                    for r in rows if r.get("events", 0) < floor]

    if not conclusive:
        return _unanswered(
            "subgroup_variation",
            f"No subgroup reaches {floor} events, so nothing can be concluded "
            f"about variation between groups.",
            f"A cohort with at least {floor} events in each group of interest.",
        )

    weakest = min(conclusive, key=lambda r: r["roc_auc_ci"][0])
    strongest = max(conclusive, key=lambda r: r["roc_auc"])
    errors = {}
    for row in conclusive:
        observed = row.get("observed")
        if observed:
            errors[row["group"]] = round(
                abs(row["mean_predicted"] - observed) / observed, 4
            )
    worst_error = max(errors.items(), key=lambda kv: kv[1]) if errors else (None, None)
    overall = card["validation_metrics"]["primary"]["roc_auc"]

    evidence = {
        "event_floor_for_a_conclusion": floor,
        "overall_roc_auc": overall,
        "by_group": [
            {"group": r["group"], "n": r["n"], "events": r["events"],
             "roc_auc": r["roc_auc"], "roc_auc_ci": r.get("roc_auc_ci"),
             "mean_predicted": r.get("mean_predicted"), "observed": r.get("observed"),
             "relative_error": errors.get(r["group"])}
            for r in conclusive
        ],
        "weakest_group": {"group": weakest["group"], "roc_auc": weakest["roc_auc"],
                          "roc_auc_ci": weakest["roc_auc_ci"]},
        "worst_relative_error": {"group": worst_error[0], "error": worst_error[1]},
        "groups_without_enough_events": underpowered,
    }
    note = ""
    if underpowered:
        note = (f" {len(underpowered)} group(s) have fewer than {floor} events "
                f"({', '.join(r['group'] for r in underpowered)}) and are "
                f"excluded from these comparisons rather than quoted - an "
                f"estimate from that few events is compatible with almost "
                f"anything.")
    return Answer(
        "subgroup_variation", ANSWERED,
        f"Yes, materially. Among groups with at least {floor} events, "
        f"discrimination ranges from {weakest['roc_auc']} in "
        f"{weakest['group']} to {strongest['roc_auc']} in "
        f"{strongest['group']}, against {overall} overall - most of the "
        f"overall figure comes from age separating young from old, so within "
        f"a narrow age band there is much less signal. The largest error in "
        f"predicted level is {worst_error[1]:.1%} in {worst_error[0]}." + note,
        evidence, ["meta"],
    )


def _transportability(card, clinical, external) -> Answer:
    if not external or not card:
        return _unanswered(
            "transportability",
            "The model has not been scored on any population outside the "
            "survey it was developed in.",
            "Run the external validation harness on a registered cohort.",
        )
    discrimination = external["discrimination"]
    internal = discrimination["internal_roc_auc"]
    low = discrimination["roc_auc_ci"][0]
    events = discrimination["events"]

    # Established means the interval rules out a drop that would matter. An
    # interval that spans both "as good as internal" and "materially worse"
    # answers nothing, however comfortable its midpoint looks.
    rules_out_a_meaningful_drop = (internal - low) <= MEANINGFUL_AUC_DROP
    enough = events >= MIN_EVENTS_FOR_A_CONCLUSION
    degraded = discrimination["roc_auc_ci"][1] < internal - MEANINGFUL_AUC_DROP

    ethnicity = external.get("discrimination_by_ethnicity", [])
    unsupported = [row["group"] for row in ethnicity
                   if not row.get("conclusion_supported")]
    evidence = {
        "external_roc_auc": discrimination["roc_auc"],
        "external_roc_auc_ci": discrimination["roc_auc_ci"],
        "internal_roc_auc": internal,
        "events": events,
        "meaningful_drop_threshold": MEANINGFUL_AUC_DROP,
        "interval_rules_out_a_meaningful_drop": bool(rules_out_a_meaningful_drop),
        "calibration_transport_tested": external.get("calibration_reported", False),
        "groups_without_enough_events": unsupported,
        "replication": external.get("replication", []),
    }
    broken = [row for row in external.get("replication", [])
              if not row.get("replicates")]
    if broken:
        evidence["findings_that_did_not_replicate"] = broken

    if degraded:
        return Answer(
            "transportability", ANSWERED,
            f"No. Discrimination is degraded on the external population: "
            f"{discrimination['roc_auc']} against {internal} internally, and "
            f"the interval excludes agreement.",
            evidence, ["meta", "external"],
        )
    if rules_out_a_meaningful_drop and enough:
        return Answer(
            "transportability", PARTIAL,
            f"Discrimination transports to the external population "
            f"({discrimination['roc_auc']}, and the interval rules out a drop "
            f"larger than {MEANINGFUL_AUC_DROP}). Calibration transport is "
            f"still untested, and the intended population is not this one.",
            evidence, ["meta", "external"],
            to_answer_this=(
                "A cohort from the intended population, with follow-up over the "
                "model's full horizon so that calibration can also be checked."
            ),
        )
    return Answer(
        "transportability", UNANSWERED,
        f"Not established either way. On the external population ROC-AUC is "
        f"{discrimination['roc_auc']} (95% CI {low}-"
        f"{discrimination['roc_auc_ci'][1]}) against {internal} internally. "
        f"The interval is equally compatible with performance holding and with "
        f"it falling to {low}, which would be materially worse; at {events} "
        f"events the study cannot separate those. "
        + (f"Groups with too few events for any conclusion: "
           f"{', '.join(unsupported)}. " if unsupported else "")
        + (f"{len(broken)} finding(s) from development did not replicate."
           if broken else ""),
        evidence, ["meta", "external"],
        to_answer_this=(
            "A cohort from the intended population with enough events to "
            "narrow the interval - roughly, enough that the lower bound sits "
            f"within {MEANINGFUL_AUC_DROP} of the point estimate - and with "
            "follow-up over the model's full horizon."
        ),
    )


BUILDERS = {
    "development_population": _development_population,
    "validation_populations": _validation_populations,
    "representation": _representation,
    "exclusions": _exclusions,
    "abstention_rate": _abstention_rate,
    "abstention_reasons": _abstention_reasons,
    "discrimination": _discrimination,
    "calibration": _calibration,
    "subgroup_variation": _subgroup_variation,
    "transportability": _transportability,
}


def derive_missing_evidence(answers) -> Answer:
    """Question 11, computed from the other ten.

    This is deliberately not something a person writes. A hand-written
    limitations section drifts away from the measurements the moment the
    measurements change, and it drifts in one direction.
    """
    open_questions = [
        {
            "key": answer.key,
            "question": _BY_KEY[answer.key].text,
            "status": answer.status,
            "to_answer_this": answer.to_answer_this,
        }
        for answer in answers
        if answer.key != DERIVED_KEY and answer.status != ANSWERED
    ]
    if not open_questions:
        return Answer(
            DERIVED_KEY, ANSWERED,
            "Every question in this set is answered by a recorded measurement. "
            "That is a statement about this question set, not about the model "
            "being safe - the set can only ask what it knows to ask.",
            {"open_questions": []}, [],
        )
    return Answer(
        DERIVED_KEY, ANSWERED,
        f"{len(open_questions)} of {len(QUESTIONS) - 1} questions are not "
        f"fully answered: "
        + ", ".join(q["key"] for q in open_questions)
        + ". Each is listed below with what would close it.",
        {"open_questions": open_questions,
         "unanswered": [q["key"] for q in open_questions
                        if q["status"] == UNANSWERED],
         "partial": [q["key"] for q in open_questions
                     if q["status"] == PARTIAL]},
        [],
    )


# --- assembly -------------------------------------------------------------
def _load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else ""


def _answer(key, card, clinical, external) -> Answer:
    """Ask one question, and treat an artifact that cannot answer it as a gap.

    Model cards from older pipelines - and from any future one - will not all
    carry the same fields. The wrong response to that is a crash, which stops
    the whole dossier being produced; the other wrong response is a silently
    skipped question. Both end with a record that says less than it should
    without saying that it does.
    """
    try:
        return BUILDERS[key](card, clinical, external)
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        return _unanswered(
            key,
            f"The recorded artifacts do not contain what this question needs "
            f"({type(error).__name__}: {error}). Nothing is claimed either way.",
            "Regenerate this model's artifacts with the current pipeline, which "
            "records the fields this question reads.",
        )


def build_dossier(version: str, artifacts: Path = ARTIFACTS) -> dict:
    paths = {
        "meta": artifacts / f"cvd-{version}.meta.json",
        "clinical": artifacts / f"cvd-{version}.clinical.json",
        "external": artifacts / f"cvd-{version}.external.json",
    }
    card = _load(paths["meta"])
    clinical = _load(paths["clinical"])
    external = _load(paths["external"])

    answers = [_answer(question.key, card, clinical, external)
               for question in QUESTIONS if question.key != DERIVED_KEY]
    answers.append(derive_missing_evidence(answers))

    problems = check_coherent(answers)
    if problems:
        raise AssertionError(
            "the dossier is internally inconsistent: " + "; ".join(problems)
        )

    counts = {status: sum(1 for a in answers if a.status == status)
              for status in (ANSWERED, PARTIAL, UNANSWERED)}
    return {
        "questions_version": QUESTIONS_VERSION,
        "model_version": version,
        "model_id": (card or {}).get("model_id", ""),
        "sources": {name: {"present": path.exists(), "sha256_16": _digest(path)}
                    for name, path in paths.items()},
        "status_counts": counts,
        "fully_answered": counts[PARTIAL] == 0 and counts[UNANSWERED] == 0,
        "answers": [answer.as_dict() for answer in answers],
    }


def check_coherent(answers) -> list[str]:
    """Rules the dossier must satisfy to be worth reading at all."""
    problems = []
    keys = [answer.key for answer in answers]
    if keys != [question.key for question in QUESTIONS]:
        problems.append("the answers do not match the question set, in order")

    for answer in answers:
        if answer.status not in (ANSWERED, PARTIAL, UNANSWERED):
            problems.append(f"{answer.key}: unknown status {answer.status!r}")
        if answer.status != ANSWERED and not answer.to_answer_this.strip():
            problems.append(
                f"{answer.key} is {answer.status} but does not say what would "
                f"answer it - a gap with no route out of it is an excuse"
            )
        if answer.status == ANSWERED and answer.key != DERIVED_KEY and not answer.sources:
            problems.append(
                f"{answer.key} claims to be answered but names no source artifact"
            )
        if not answer.answer.strip():
            problems.append(f"{answer.key}: empty answer")

    derived = next((a for a in answers if a.key == DERIVED_KEY), None)
    expected = {a.key for a in answers
                if a.key != DERIVED_KEY and a.status != ANSWERED}
    if derived is not None:
        listed = {q["key"] for q in derived.evidence.get("open_questions", [])}
        if listed != expected:
            problems.append(
                f"the missing-evidence list does not match the measurements: "
                f"lists {sorted(listed)}, measured {sorted(expected)}"
            )
    return problems


# --- reporting ------------------------------------------------------------
_MARK = {ANSWERED: "answered ", PARTIAL: "PARTIAL  ", UNANSWERED: "UNANSWERED"}


def _wrap(text: str, width: int = 74, indent: str = " " * 6) -> str:
    import textwrap

    return textwrap.fill(text, width=width, initial_indent=indent,
                         subsequent_indent=indent)


def print_dossier(dossier: dict) -> None:
    print(f"=== evidence dossier: {dossier['model_id']}:"
          f"{dossier['model_version']} ===")
    print(f"question set {dossier['questions_version']}")
    for name, source in dossier["sources"].items():
        state = source["sha256_16"] if source["present"] else "MISSING"
        print(f"  {name:<10} {state}")
    print()
    for index, answer in enumerate(dossier["answers"], start=1):
        print(f"{index:>3}. [{_MARK[answer['status']]}] {answer['question']}")
        print(_wrap(answer["answer"]))
        if answer["to_answer_this"]:
            print(_wrap("What would answer it: " + answer["to_answer_this"]))
        print()
    counts = dossier["status_counts"]
    print(f"answered {counts[ANSWERED]}   partial {counts[PARTIAL]}   "
          f"unanswered {counts[UNANSWERED]}")
    if not dossier["fully_answered"]:
        print("This model has open evidence gaps. That is a statement of fact "
              "about what has been")
        print("measured, not a defect to be argued away. Any approval to use "
              "it clinically has to")
        print("name these gaps explicitly.")


def main(version: str = "3.1.0") -> int:
    try:
        dossier = build_dossier(version)
    except AssertionError as error:
        print(error)
        return 2
    print_dossier(dossier)
    destination = ARTIFACTS / f"cvd-{version}.evidence.json"
    destination.write_text(json.dumps(dossier, indent=2, default=str))
    print(f"\nwrote {destination}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="3.1.0")
    sys.exit(main(parser.parse_args().version))
