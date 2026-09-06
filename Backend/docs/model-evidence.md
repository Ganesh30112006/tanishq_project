# The evidence dossier

Every model in this system has to be able to answer eleven questions. Ten are
about what has been measured. The eleventh is about what has not.

```
 1. Where was it developed?
 2. Where was it validated?
 3. Who was represented?
 4. Who was excluded?
 5. How often does it abstain?
 6. Why does it abstain?
 7. How well does it discriminate?
 8. How well calibrated is it?
 9. Does performance vary by subgroup?
10. Does performance transport?
11. What evidence is still missing?
```

The pipeline already measured most of this. What it did not have was a single
place that asked the same questions of every model, in the same order, and made
the *absence* of an answer as visible as its presence.

```
python -m intelligence.ml_service.evidence --version 3.1.0
```

writes `cvd-<version>.evidence.json` beside the model card, and
`register_model` stores it on the `ModelVersion`. `manage.py model_evidence
--gaps-only` reads it back from the registry.

## Three rules that make this a governance artifact

**An unanswered question is an output, not an omission.** Every question gets
`answered`, `partial` or `unanswered`, and anything short of `answered` must
carry `to_answer_this`: the specific data or run that would close it. A gap
with no route out of it is an excuse, and `check_coherent` rejects the dossier
if one appears. A question whose artifact is simply missing does not quietly
vanish - it comes back as `unanswered` naming the artifact.

**Question 11 is derived, never written.** It is exactly the set of the other
ten that are not fully answered. A hand-written limitations section drifts away
from the measurements the moment the measurements change, and it drifts in one
direction. `check_coherent` rejects a dossier whose gap list disagrees with its
own statuses, and a test asserts that.

**A conclusion needs enough evidence to support it, not just a point
estimate.** This is the rule that does the most work. Transportability for
3.1.0 has a comfortable-looking midpoint - external ROC-AUC 0.7116 against
0.7653 internally - and an interval running down to 0.6611. That interval is
equally compatible with the model working and with it being materially worse,
so transport is reported as **unanswered**, not as "broadly similar". The
threshold is stated in the module: a drop of `MEANINGFUL_AUC_DROP = 0.05` would
change whether the tool is worth using, so transport counts as established only
when the interval rules that out.

## What 3.1.0 currently answers

| | |
|---|---|
| answered | 7 |
| partial | 3 |
| unanswered | 1 |

The four that are open, and why:

**Representation (partial).** The development cycles coded ethnicity with
`RIDRETH1`, which has no Asian category at all. The number of participants from
the intended population is therefore not small - it is *unknown and
unrecoverable from this data*. That is a different problem from a small group,
because no amount of resampling the same survey fixes it. The dossier keeps the
two apart deliberately.

**Exclusions (partial).** The stated exclusion criteria are recorded, and so
are the 1,050 of 16,097 people refused a score at the point of use. What was
missing is the construction ladder for the development cohort - how many people
each build step removed. It was printed when the cohort was built and thrown
away, so the only place that answer ever existed was a terminal scrollback.
`nhanes_cohort` now writes `<cohort>.derivation.json` at build time, so the next
trained version answers this; it cannot be reconstructed for a version already
fitted, and the dossier says so rather than pretending otherwise.

**Calibration (partial).** Measured internally (slope 0.9539). Not measured on
any external population and, with the current linkage, not measurable: only 5
years of follow-up exist for a model that predicts 10.

**Transportability (unanswered).** See above.

Two kinds of exclusion are reported separately and never summed. Someone
dropped when the dataset was built was never in the model's world. Someone
refused at the point of use is in front of a clinician right now and gets
nothing.

## One definition per statistic

The first version of question 9 reported a worst subgroup calibration error of
42%, beside an acceptance-criteria file reporting a pass at 19.4%. Both were
"the worst relative error by subgroup"; they differed because the criteria
apply an event floor and the dossier did not, and the 42% came from a group
with 21 events. A reader had no way to tell which number to believe.

Question 9 now uses `acceptance_criteria.MIN_SUBGROUP_EVENTS` and computes the
error the same way, and a test asserts the dossier's worst group and figure
appear in the criteria file's own recorded observation.

## Approving a model has to name what is unknown

A dossier is worth nothing if a model can reach live clinical use without
anyone reading it. So `ModelGovernanceService.transition` now refuses
`APPROVED_FOR_CLINICAL_REVIEW` when the version has no dossier at all, and
refuses it when the dossier has open questions the approval does not name:

```
manage.py govern_model --model cvd-nhanes-logreg --model-version 3.1.0 \
    --to APPROVED_FOR_CLINICAL_REVIEW --by cmo@example.com \
    --reason "supervised use, every output clinician-reviewed" \
    --acknowledge-gap transportability --acknowledge-gap calibration \
    --acknowledge-gap representation --acknowledge-gap exclusions
```

The rule is deliberately **not** "a model with gaps cannot be approved". Every
useful clinical model has gaps, and blocking them would not remove them - it
would move them out of the record and into somebody's private judgement, which
is the one place they cannot be audited. What is blocked is approving
*silently*. The acknowledged keys land in the `ModelLifecycleEvent`, which is
append-only, so a later dossier can close a gap but cannot make it look as
though the gap was never there when somebody signed.

`seed_demo` goes through the same gate. The demonstration model is fitted on
invented data and its dossier is almost entirely open questions, so seeding
lists every one of them in the approval reason and evidence. The last time that
command had a shortcut, it put a synthetic model in front of a live task.

The dossier itself is *not* part of the immutable comparison in
`register_model`. The model is fixed; the evidence about it is meant to
accumulate. A validation run on a new cohort next year adds to what is known
without changing a single weight, and freezing the dossier at approval time
would make the record permanently claim less than is known.

## Adding a cohort

`cohort_contract.py` exists so that when a genuine Indian longitudinal cohort
becomes available it goes through *exactly the same* pipeline, judged against
*exactly the same* rules. Otherwise the comparison between what the US data
showed and what the local data shows is not a comparison at all.

```python
from intelligence.ml_service.cohort_contract import CohortSpec, EXTERNAL, register

SPEC = CohortSpec(
    key="...", label="...",
    provenance="who collected it, when, under what protocol",
    country="India", examined="2019-2021",
    outcome="cardiovascular death",
    outcome_source="how death and its cause were ascertained",
    horizon_months=120,
    ethnicity_scheme="how the group column is coded",
    role=EXTERNAL,
    consent_basis="the basis on which these records may be used",
)

def load():
    ...   # a frame satisfying CONTRACT

register(SPEC, load)
```

Then `python -m intelligence.ml_service.external_validation --cohort <key>`.
Nothing in the judging changes, which is the point: a cohort cannot be made to
look better by being loaded differently.

What the contract enforces:

* **A cohort declares itself.** Provenance, country, examination period, how
  the outcome was ascertained, how the group column is coded, the role it
  plays, and the basis on which the records may be used. A spec missing any of
  these will not construct. A key cannot be silently redefined, so two reports
  carrying one name describe one population.
* **The frame is checked before anything is scored.** Missing outcome, missing
  model feature, a non-binary outcome, no events at all, or rows whose
  follow-up is unknown are hard problems and stop the run - a person with
  unknown follow-up is not a person who survived. A missing group column is a
  *soft* problem: it removes a question rather than stopping the run, because
  subgroup reliability without a group column is no answer, not a weaker one.
  All problems are reported at once.
* **The calibration rule belongs to the horizon, not to a judgement call.**
  `calibration_reportable(spec, model_horizon_months)` is the single place that
  decides. A cohort observed for less time than the model predicts would
  produce a slope that is wrong by construction and reads like a finding; so
  would one observed for longer. Only a matching horizon permits calibration,
  and the refusal reason is written into the report.

`external_validation.py` is now one implementation of that contract rather than
a bespoke script - `HORIZON_MONTHS` comes from its spec, and the sentence
attached to the population name comes from the declared `role`, so a cohort
used in development can never be described as if it had not been.

## Files

| File | Purpose |
|---|---|
| `intelligence/ml_service/evidence.py` | The eleven questions and the dossier |
| `intelligence/ml_service/cohort_contract.py` | What a cohort must declare and provide |
| `apps/risk/governance.py` | The acknowledgement rule at approval |
| `apps/risk/management/commands/model_evidence.py` | Read the dossier back from the registry |
| `tests/integration/test_evidence_dossier.py` | A gap must survive into the record |
| `tests/integration/test_cohort_contract.py` | The rules do not bend per cohort |
| `tests/clinical/test_evidence_governance.py` | Approval has to name what is unknown |
