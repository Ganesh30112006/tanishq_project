# Training the cardiovascular risk model

The model the application serves is trained on **real data with a real
outcome**: the US CDC's NHANES survey linked to the NCHS public-use mortality
file. It replaces an earlier demonstration model fitted on a synthetic
generator, which could never be more than a placeholder because a model trained
on invented data can only learn the relationships that were written into the
generator.

The version that ships is **3.0.0**, and it requires no laboratory result at
all: age, recorded sex, systolic blood pressure and whether the person smokes.

## Reproducing it

```bash
cd Backend
. .venv/Scripts/activate

# 1. Fetch NHANES 1999-2010 and the linked mortality files (~60 MB, cached).
python -m intelligence.ml_service.nhanes_download

# 2. Build the analytic cohort. Three are available - see below.
python -m intelligence.ml_service.nhanes_cohort --sample clinical

# 3. Train, validate, and write the artifact + model card.
python -m intelligence.ml_service.train_nhanes \
    --version 3.0.0 --features clinical --cohort clinical

# 4. Check that every coefficient is safe to show a patient as a reason.
python -m intelligence.ml_service.diagnostics \
    --cohort clinical --features clinical --baseline clinical

# 5. Register it, then move it through the governed lifecycle.
python manage.py register_model --meta intelligence/_artifacts/cvd-3.0.0.meta.json
python manage.py govern_model --model cvd-nhanes-logreg --model-version 3.0.0 \
    --to VALIDATION --by <approver-email> --reason "..."
```

`register_model` always lands a new version in `DRAFT`, and **refuses to modify
a version that has left DRAFT** - see "A version means one model" below. Making
it live requires `govern_model` with a named approver and a recorded reason, so
a person always stands behind a clinical model.

## The data

| | |
|---|---|
| Source | NHANES 1999-2000 through 2009-2010 (6 cycles) |
| Outcome | NCHS linked mortality, public-use file, follow-up through 2019 |
| Event | Death with underlying cause *diseases of heart* (leading-cause recode 001) or *cerebrovascular disease* (005) within 120 months of examination |
| Population | Adults aged 40-79 at examination, not pregnant, eligible for mortality linkage, all required features measured |
| Cohort | 15,368 participants, **771 real cardiovascular deaths** (5.02%) |

The derivation prints every exclusion step and how many people it removed, so
the cohort can be argued with rather than taken on trust.

### Three cohorts, and why the smallest one was the wrong one

Every measurement a cohort insists on is people it throws away. Since the
binding constraint on every conclusion in this document is the number of
**events**, asking for less data can be worth far more than asking for better
data.

| `--sample` | Requires | n | Events |
|---|---|---|---|
| `fasting` | fasting glucose (+ HDL) | 6,994 | 330 |
| `full` | HbA1c (+ HDL) | 14,317 | 662 |
| **`clinical`** | **no laboratory result** | **15,368** | **771** |

Fasting glucose is only drawn in NHANES' morning subsample, so requiring it
halves the survey. HbA1c is measured on everyone and needs no fast, which
doubles the cohort - and HbA1c turned out to add nothing to discrimination
(removing it moved AUC by 1e-6), so the laboratory requirement was dropped
entirely.

### The people a measurement requirement excludes

This is the most important finding here, and it is not about the model.

**The 282 participants who could not be weighed and measured have a 10-year
cardiovascular death rate of 18.8%, against 4.76% for everyone else.** Their
all-cause mortality inside the window is 48%. They are on average five years
older. They are people too ill or too disabled to stand on a scale.

Every earlier model in this project silently excluded all of them, by requiring
either BMI or a blood test. That is not a neutral technicality: a screening tool
whose cohort excludes the sickest people reports a performance figure earned on
an easier population than the one it will be used on. When they are included,
the headline AUC falls from 0.7782 to 0.7653. **The lower number is the honest
one.** The higher one was flattered by their absence.

So the `clinical` cohort requires nothing that a frail person cannot provide,
and BMI is carried in the file but not required, because no shipped model reads
it.

### Three choices worth disagreeing with explicitly

- **Censoring.** Participants still alive with under 120 months of follow-up
  cannot have their 10-year status known, so they are excluded rather than
  quietly counted as survivors.
- **Competing risk.** Death from a non-cardiovascular cause inside the window is
  counted as a non-event. That is the conventional binary framing and it biases
  absolute risk *downward*, most in the oldest patients. `--drop-competing` runs
  the sensitivity analysis.
- **Physiologic plausibility.** NHANES publishes a glycohemoglobin of 2.0%,
  which converts to a *negative* mmol/mol value; a haemoglobin variant defeats
  the assay and the result is reported anyway. Values outside a deliberately
  wide possibility range are **voided rather than dropped**, so an impossible
  HDL does not remove someone from a model that never reads HDL. This matters
  beyond tidiness: the served `valid_domain` gate is derived from these same
  percentiles, so training on impossible values would widen the gate that exists
  to refuse impossible values from real patients.

## Validation design

Development uses cycles **1999-2006**; the test set is cycles **2007-2010** - a
later period, different people, never seen during fitting or calibration. This
is a genuine temporal external validation. A random split would have been kinder
to the model and would have answered a less useful question.

A leakage guard asserts that no participant id appears in more than one split;
it raises rather than warns.

**The calibration method is chosen on development data only.** A logistic
regression already emits a probability, so a calibrator is not automatically an
improvement - and on this feature set it is not one. Which method wins is
decided by 5-fold cross-validation inside the development cycles, scored by
Brier, with the test cycles never touched:

| Method | Dev Brier (5-fold) |
|---|---|
| **none** | **0.044496** |
| Platt | 0.044599 |
| isotonic | 0.045008 |

Trying all three on the test set and keeping the best would have turned the
reported calibration slope into a best-of-three on the very data the headline
numbers are supposed to be honest about.

## What the numbers actually say

On the held-out 2007-2010 period (n = 5,351, **272 events**):

| Model | Features | ROC-AUC | 95% CI | Brier | Calib. slope |
|---|---|---|---|---|---|
| Age alone | 1 | 0.7409 | 0.712-0.769 | — | — |
| **Clinical (3.0.0, ships)** | **4** | **0.7653** | **0.740-0.789** | **0.04621** | **0.954** |
| Gradient boosting | 4 | 0.7561 | 0.730-0.781 | 0.04673 | 0.768 |

Read the first row before the others. **Age alone scores 0.7409.** A paired
bootstrap of the AUC difference on the same patients says:

- clinical (3.0.0) vs age alone: **+0.0244 (95% CI +0.0092 to +0.0399)**

That interval excludes zero, so the shipped model can be *shown* to beat
knowing the patient's age rather than merely scoring higher than it.

This needs stating carefully, because the previous model card claimed the
opposite and was wrong to. Version 2.4.0 shipped with the phrase "NOT
statistically significant" **hardcoded** into its card. That sentence was
written when the comparison had been run for two *other* feature sets, and it
was never re-measured for the set that actually shipped. Measured properly,
2.4.0's own difference against age alone was +0.0295 (95% CI +0.0028 to
+0.0566) - already significant, and understated by its own documentation. A
model card is not a place for a conclusion someone typed once: the verdict is
now computed from the interval on every training run, and the card says
whichever thing is true.

What the larger cohort genuinely bought is precision. The interval is
+0.0092 to +0.0399 at 272 events, against +0.0028 to +0.0566 at 128 - roughly
half the width, from no longer excluding people for lacking a measurement no
model uses.

Calibration is good without any calibrator: the slope is 0.954 where 1.0 is
perfect, and predicted risk tracks observed risk across deciles from 0.5% to
16.5%. That matters more than AUC for a number shown to a person - a
well-calibrated 5% means 5%.

Standardised coefficients (log-odds per SD), all pointing the way the biology
does:

| Feature | Coefficient | AUC without it |
|---|---|---|
| age | 0.985 | 0.6103 |
| current_smoker | 0.3041 | 0.7534 |
| is_male | 0.2732 | 0.7544 |
| systolic_bp | 0.2374 | 0.7632 |

## Where it is weak

Measured, not guessed. All of these are written into the model card's
`known_failure_modes` by the training run itself:

- **Discrimination within an age band collapses.** Overall AUC 0.765, but 0.594
  in ages 70-79 and 0.672 in 55-69. Most of the headline number is age
  separating the young from the old.
- **Under-prediction in the oldest patients**: predicted 11.8% against observed
  12.6% in ages 70-79, and 4.95% against 6.14% in Black non-Hispanic
  participants. Partly the competing-risk framing above.
- **No laboratory result is used at all.** That is what makes the model usable
  outside a clinic, and it is also a real limit: it cannot see a blood sugar, a
  cholesterol or a kidney function. A normal score is not evidence that those
  are normal and must never be read as a reason not to test them.
- **Not validated in an Indian population.** Trained on a US survey. South Asian
  cardiovascular risk at a given risk-factor level is generally higher, so the
  calibration that looks good here should not be assumed to hold.

## Is it defensible, not just accurate?

Accuracy is measured on the people the model *could* score. That is not the
population it will be pointed at, and the gap between the two is where the
clinically important failures live. `clinical_validation.py` asks the questions
the training battery cannot:

```bash
python -m intelligence.ml_service.clinical_validation --version 3.1.0
```

It judges the model against `acceptance_criteria.py`, which states each
threshold **and the clinical reason for it**, separately from the code that
measures it. Criteria written after seeing a result are not criteria, they are a
description of that result. The file records an honest caveat about its own
first version: the coverage thresholds were written after the first coverage
numbers existed, because until that analysis was run nobody knew coverage was a
question. They are justified on clinical grounds rather than fitted to let the
current model pass - and the current model fails one of them.

The run exits non-zero on failure, so it can gate a build.

### Coverage: who can this actually serve?

Of **16,097** adults aged 40-79 with a known 10-year outcome:

| | People | Event rate |
|---|---|---|
| Can be scored | 15,047 (93.5%) | 4.92% |
| Refused - a required input was never recorded | 729 | 5.32% |
| Refused - a value outside the validated range | 321 | 9.94% |

### The refusal that was hiding the worst readings

Splitting that last row by which bound was crossed is the finding that changed
the code:

| Breach | People | Event rate |
|---|---|---|
| Systolic BP **above** the validated 193.3 | 137 | **16.06%** |
| Systolic BP below the validated 94.0 | 184 | 4.89% |

The people refused for a blood pressure above the ceiling die of cardiovascular
causes at **more than three times** the rate of the people the model serves. The
ones below the floor are indistinguishable from the served population.

Both used to receive the same message - *"This tool was not built for a record
like yours."* True, and for the first group it reads as a shrug at the single
most alarming number in their record.

The model still may not extrapolate: a risk estimate at a reading it was never
fitted on would be invented. But it may not be silent either. The feature schema
now carries `risk_direction` - the sign of each fitted coefficient, written at
registration - so the sufficiency engine can tell a dangerous breach from a
harmless one, and:

- **The patient is told what was seen.** *"Your record has BP - the upper number
  saved as 204. That is above the range this tool was tested on, so it has not
  given an estimate - any number would be unreliable. Please show this reading
  to a doctor."* No estimate, no diagnosis, no invented value: it repeats a
  reading already in the record and routes it.
- **The clinician gets the reason in the limitations**, naming the value, the
  bound and the direction.
- The response carries `reading_needs_review` so a front end can escalate rather
  than showing a dead end.

### Coverage is not equal, and that is still open

| Group | Refused |
|---|---|
| White non-Hispanic | 5.07% |
| Mexican American | 6.96% |
| Other Hispanic | 7.06% |
| Black non-Hispanic | 8.80% |
| Other/multiple | 10.43% |

`coverage.group_disparity` **FAILS** at 2.06x against a 1.5x ceiling. It is
driven almost entirely by a missing systolic blood-pressure reading - 714 of the
729 missing-input refusals - so no change to the model or its code will fix it.
It is a measurement-completeness problem in whoever collects the data, and it is
recorded as an open finding rather than waived. Unequal coverage is unequal
care, and it appears in no accuracy metric.

### Clinical utility, in units a clinician can plan with

At a **5% 10-year risk of cardiovascular death** decision threshold - a
placeholder that a responsible clinician must replace, recorded in
`acceptance_criteria.DECISION_THRESHOLD` so the assumed number is visible:

| | |
|---|---|
| Flagged | 1,833 of 5,351 (34.3% of the list) |
| Deaths caught | 194 of 272 (71.3%) |
| Flagged per death caught | 9.4 |
| Net benefit | +0.02013, against +0.00088 for treating everyone |

Net benefit says acting on the output beats both strategies that need no model.
The other three rows are what a clinic actually plans around.

### The current verdict

**9 of 10 criteria pass.** The one failure is `coverage.group_disparity`, above.
Two are worth calling out as passing narrowly rather than comfortably:
`discrimination.subgroup_above_chance` is carried by ages 70-79 at a lower bound
of 0.546, and `calibration.subgroup_error` by Black non-Hispanic participants at
19.4% relative under-prediction against a 25% ceiling.

A criterion that cannot be measured is reported as `not assessed` and does not
count as a pass - "we checked and it was fine" and "there was nothing to check"
are different claims.

## Why BMI is not in the model

BMI is not excluded for being weak. It is excluded for being **bent**.

Ten-year cardiovascular death is U-shaped in BMI. In this cohort the *leanest*
quintile has the highest event rate of all five:

| BMI quintile | Event rate |
|---|---|
| ≤ 24.15 | **5.07%** |
| 24.15-26.98 | 4.53% |
| 26.98-29.73 | **4.22%** |
| 29.73-33.65 | 4.64% |
| > 33.65 | 5.34% |

The same U appears within the 55-69 age band, so it is not an age artefact. Low
weight in older adults is frequently illness and frailty rather than health.

A linear coefficient cannot represent a U. The one that gets fitted is positive
(+0.157), and it is perfectly sign-stable - so it passes every check this
project had. And it tells a frail patient with a BMI of 20 that their weight is
*reducing* their risk, when their observed risk is the highest of any BMI group.
That is the same failure HDL was excluded for: this system shows per-feature
contributions to patients, and a reason that points the wrong way is worse than
no reason.

It buys almost nothing. AUC 0.7782 with BMI against 0.7735 without, a paired
bootstrap difference of +0.0047 whose lower bound is +0.0001. Every non-linear
encoding tried - `|BMI - 27|`, `BMI + BMI²` - buys no more and is not
significant at all.

### The check that catches this

Sign stability cannot see a bend, which is why `diagnostics.py` now also runs a
**shape check**. For each feature it compares the observed event rate across
quintiles against the direction the fitted coefficient claims.

It deliberately does *not* fail on every non-monotonicity. Blood pressure bends
too - the very lowest readings carry slightly more risk than the next band up -
and telling someone with a low reading that it helps them is both true and
harmless, because the low end really is the low-risk end. The test is narrower
and targets the actual harm: **take the end of the range the coefficient treats
as protective, and ask whether it is genuinely low risk.** BMI fails that. Blood
pressure passes it.

The current shipped feature set passes all three checks - sign stability,
adjusted-vs-unadjusted agreement, and shape - so every feature in it is safe to
show a patient as a reason.

## Sex is never inferred

`FeatureAssembler._is_male` returns a value only for `MALE` and `FEMALE`. For
`INTERSEX` and `UNKNOWN` it returns nothing, the feature lands in `not_found`,
and the sufficiency engine blocks the prediction. Filling in the more common
value would be inventing a clinical fact about a real person, and the model was
never fitted on anyone the record describes that way.

## Smoking is a dated measurement, not a note

Smoking is recorded as `MeasurementKind.SMOKING_STATUS`, so it inherits the same
machinery as every other model input: a clinical data state, an observation date,
and the freshness rule that blocks a prediction built on a stale answer. Someone
who smoked two years ago may have stopped, and the system knows to ask again
rather than reusing it.

**"Not recorded" is not "does not smoke".** An unrecorded status blocks the
prediction. Defaulting it to zero would have quietly under-estimated risk for
exactly the population least likely to have been asked.

## A version means one model

`register_model` used to `update_or_create` with `lifecycle_state=DRAFT` in the
defaults, so re-running it on an existing version reset that version's state and
overwrote its weights, domain, metrics and card. Two things broke, both
silently.

**RETIRED stopped being terminal.** The governance table gives a retired model
nowhere to go, because withdrawing a clinical model from service has to mean
something. Re-registering put it back in `DRAFT`, from where it could be walked
all the way back to serving patients. That is not hypothetical: `seed_demo`
re-registered the synthetic demonstration model on every run and took the `cvd`
task away from the real one, so a development database that looked entirely
normal was serving predictions from a model fitted on invented data - including
scoring a 31-year-old, outside any validated age range, at 13.8%.

**A version identifier stopped meaning anything.** Every `RiskAssessment` row and
audit entry refers to a model as `model_id:version`. If that registry row can be
rewritten to describe a different model, a historical clinical decision can no
longer be reconstructed.

Now: a version past `DRAFT` is immutable. Re-registering a byte-identical
artifact is a no-op, so provisioning scripts stay safe; re-registering anything
*different* is refused and names what differs. The `FeatureSchema` - which
carries the `valid_domain` gate that refuses out-of-range patients - is checked
in its own right and written only after the decision, so the check does not
depend on a transaction rollback to be correct. `seed_demo` additionally refuses
to take the `cvd` task from a model it did not install.

## Running on the Intel GPU

`gpu_arm.py` exports the fitted model to ONNX and runs it through OpenVINO on the
integrated GPU. The purpose is **validating the deployment target**, not speed:

| Device | Precision | max abs. difference vs scikit-learn | One patient |
|---|---|---|---|
| CPU (i7-1255U) | f32 | 1.3e-07 | 0.056 ms |
| Iris Xe iGPU | f16 (**default**) | **1.2e-03** | 0.441 ms |
| Iris Xe iGPU | f32 | 1.9e-07 | 0.439 ms |

**OpenVINO's GPU plugin defaults to FP16, and at FP16 the iGPU disagrees with
the validated model by up to 0.125 percentage points of absolute risk.** That is
small, but it is enough to move a patient across a follow-up threshold, and it
means the published metrics would not describe what the GPU returns. If this
model is ever served from a GPU, `INFERENCE_PRECISION_HINT` must be pinned to
`f32`.

There is no performance case for the GPU here regardless: the CPU is roughly
*eight times* faster per patient here, because dispatching to the GPU costs
far more than the handful of multiply-adds being dispatched.

`torch.xpu` is not used. It segfaults against the Intel driver on this machine
(31.0.101.4502, from 2023), and the `torch ... +xpu` build's *CPU* autograd
segfaults too. If PyTorch is wanted on this hardware, the driver needs updating
first.

## Files

| File | Purpose |
|---|---|
| `intelligence/ml_service/nhanes_download.py` | Fetch and cache the public data |
| `intelligence/ml_service/nhanes_cohort.py` | Cohort derivation, outcome definition, plausibility bounds |
| `intelligence/ml_service/train_nhanes.py` | Training, calibration selection, validation battery, model card |
| `intelligence/ml_service/evaluation.py` | Discrimination, calibration, subgroups, net benefit |
| `intelligence/ml_service/diagnostics.py` | Paired bootstrap, coefficient stability, shape check |
| `intelligence/ml_service/gpu_arm.py` | ONNX export, OpenVINO GPU validation |
| `intelligence/ml_service/train.py` | The original synthetic generator, kept for the tests |
| `tests/integration/test_nhanes_model.py` | Sex is never guessed; the calibrator is applied correctly |
| `tests/integration/test_model_pipeline_safety.py` | Units, plausibility, the shape check, the shipped card |
| `tests/integration/test_model_registration_immutability.py` | A version means one model |
