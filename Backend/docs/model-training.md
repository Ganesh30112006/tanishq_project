# Training the cardiovascular risk model

The model the application serves is trained on **real data with a real
outcome**: the US CDC's NHANES survey linked to the NCHS public-use mortality
file. It replaces an earlier demonstration model fitted on a synthetic
generator, which could never be more than a placeholder because a model trained
on invented data can only learn the relationships that were written into the
generator.

Everything below is reproducible from a clean checkout with four commands.

## Reproducing it

```bash
cd Backend
. .venv/Scripts/activate

# 1. Fetch NHANES 1999-2010 and the linked mortality files (~58 MB, cached).
python -m intelligence.ml_service.nhanes_download

# 2. Build the analytic cohort.
python -m intelligence.ml_service.nhanes_cohort

# 3. Train, validate, and write the artifact + model card.
python -m intelligence.ml_service.train_nhanes --version 2.3.0 --features deployable

# 4. Register it, then move it through the governed lifecycle.
python manage.py register_model --meta intelligence/_artifacts/cvd-2.3.0.meta.json
python manage.py govern_model --model cvd-nhanes-logreg --model-version 2.3.0 \
    --to VALIDATION --by <approver-email> --reason "..."
```

`register_model` always lands the version in `DRAFT`. Making it live requires
`govern_model` with a named approver and a recorded reason, so a person always
stands behind a clinical model.

## The data

| | |
|---|---|
| Source | NHANES 1999-2000 through 2009-2010 (6 cycles) |
| Outcome | NCHS linked mortality, public-use file, follow-up through 2019 |
| Event | Death with underlying cause *diseases of heart* (leading-cause recode 001) or *cerebrovascular disease* (005) within 120 months of examination |
| Population | Adults aged 40-79 at examination, not pregnant, eligible for mortality linkage, all features measured |
| Cohort | 6,999 participants, **331 real cardiovascular deaths** (4.73%) |

The derivation prints every exclusion step and how many people it removed, so
the cohort can be argued with rather than taken on trust.

Three choices are worth disagreeing with explicitly:

- **Censoring.** Participants still alive with under 120 months of follow-up
  cannot have their 10-year status known, so they are excluded rather than
  quietly counted as survivors. This removes 686 people, mostly from the last
  cycle.
- **Competing risk.** Death from a non-cardiovascular cause inside the window
  is counted as a non-event. That is the conventional binary framing and it
  biases absolute risk *downward*, most in the oldest patients.
  `--drop-competing` runs the sensitivity analysis: excluding those 799 deaths
  raises the event rate from 4.73% to 5.34%, which is the size of the bias.
- **Fasting subsample.** Fasting glucose is only measured in NHANES' morning
  subsample, so requiring it roughly halves the cohort and makes it a subset of
  survey participants rather than a representative sample.

## Validation design

Development uses cycles **1999-2006**; the test set is cycles **2007-2010** — a
later period, different people, never seen during fitting or calibration. This
is a genuine temporal external validation. A random split would have been
kinder to the model and would have answered a less useful question.

Calibration (Platt scaling) is fitted on a 25% slice of the development data
that the estimator never saw, so the calibrator is not fitted on its own
training predictions. A leakage guard asserts that no participant id appears in
more than one split; it raises rather than warns.

## What the numbers actually say

On the held-out 2007-2010 period (n = 2,439, 129 events):

| Model | Features | ROC-AUC | 95% CI | Brier | Calib. slope |
|---|---|---|---|---|---|
| Age alone | 1 | 0.7415 | 0.698-0.785 | — | — |
| Original five | 5 | 0.7342 | 0.693-0.775 | 0.04853 | 0.979 |
| **Deployable (ships)** | **5** | **0.7484** | **0.708-0.788** | **0.04823** | **0.993** |
| Parsimonious | 6 | 0.7640 | 0.729-0.798 | 0.04836 | 0.888 |
| Extended | 9 | 0.7658 | 0.731-0.800 | 0.04828 | 0.978 |
| Gradient boosting | 5 | 0.7393 | 0.699-0.780 | 0.04832 | 0.939 |
| Neural network (32,16) | 6 | 0.6201 | 0.570-0.668 | 0.04995 | 3.206 |

Read the first row before any of the others. **Age alone scores 0.7415.** A
paired bootstrap of the AUC difference on the same patients says:

- original five vs age alone: **−0.0085** (CI −0.031 to +0.014) — no better
- deployable vs age alone: **+0.0069** (CI −0.016 to +0.031) — not significant
- extended vs age alone: +0.0242 (CI −0.011 to +0.060) — **not significant**
- extended vs original five: +0.0327 (CI +0.008 to +0.057) — **real**

So the risk factors genuinely improve on the original feature set, but at 129
events none of these models can be *shown* to beat knowing the patient's age.
The model card says so in those words, and it must keep saying so until there
are enough events to settle it.

Calibration is the part that is unambiguously good: slope 0.993 and predicted
risk tracking observed risk across deciles from 0.6% to 14%. That matters more
than AUC for a number shown to a person — a well-calibrated 4% means 4%.

## Where it is weak

Measured, not guessed. All of these are written into the model card's
`known_failure_modes` by the training run itself:

- **Discrimination within an age band collapses.** Overall AUC 0.748, but 0.593
  in ages 70-79 and 0.630 in 55-69. Most of the headline number is age
  separating the young from the old.
- **Under-prediction in the oldest patients**: predicted 9.5% against observed
  13.3% in ages 70-79. Partly the competing-risk framing above.
- **Not validated in an Indian population.** Trained on a US survey. South
  Asian cardiovascular risk at a given risk-factor level is generally higher,
  so the calibration that looks good here should not be assumed to hold.

## Why HDL and total cholesterol are not in the model

`diagnostics.py` bootstraps the coefficients. HDL's association with the
outcome is **negative unadjusted (−0.113) and positive adjusted (+0.142)**, and
its confidence interval crosses zero. Total cholesterol's sign is a coin flip
(stability 0.500).

That matters here more than it would elsewhere, because this system shows
per-feature contributions *to patients*. A positive HDL coefficient generates
the sentence "your good cholesterol is increasing your risk", which is
clinically backwards and points a patient the wrong way. Features whose sign is
not stable are excluded rather than displayed with a caveat.

The shipped model's six coefficients all point the way the biology does: age,
male sex, systolic blood pressure, glucose and BMI all increase estimated risk.

## Why smoking is not in the model

It should be — it is in the parsimonious model and it helps. But **smoking
status has no field anywhere in the data model**, so the application cannot
assemble it and a model requiring it cannot be served. Capturing it is the
single highest-value change available to this model: it is the one established
risk factor that is missing and cheap to collect.

`--features parsimonious` trains that model today; it just cannot be deployed
until the record can hold the input.

## Sex is never inferred

`FeatureAssembler._is_male` returns a value only for `MALE` and `FEMALE`. For
`INTERSEX` and `UNKNOWN` it returns nothing, the feature lands in `not_found`,
and the sufficiency engine blocks the prediction. Filling in the more common
value would be inventing a clinical fact about a real person, and the model was
never fitted on anyone the record describes that way.

## Running on the Intel GPU

`gpu_arm.py` exports the fitted model to ONNX and runs it through OpenVINO on
the integrated GPU. The purpose is **validating the deployment target**, not
speed:

| Device | Precision | max abs. difference vs scikit-learn | One patient |
|---|---|---|---|
| CPU (i7-1255U) | f32 | 7.6e-08 | 0.16 ms |
| Iris Xe iGPU | f16 (**default**) | **6.4e-04** | 0.26 ms |
| Iris Xe iGPU | f32 | 9.7e-08 | 0.34 ms |

**OpenVINO's GPU plugin defaults to FP16, and at FP16 the iGPU disagrees with
the validated model by up to 0.064 percentage points of absolute risk.** That is
small, but it is enough to move a patient across a follow-up threshold, and it
means the published metrics would not describe what the GPU returns. If this
model is ever served from a GPU, `INFERENCE_PRECISION_HINT` must be pinned to
`f32`.

There is no performance case for the GPU here regardless: the CPU is roughly
twice as fast per patient, because dispatching to the GPU costs more than the
six multiply-adds being dispatched.

`torch.xpu` is not used. It segfaults against the Intel driver on this machine
(31.0.101.4502, from 2023), and the `torch ... +xpu` build's *CPU* autograd
segfaults too — `loss.backward()` crashes the process. If PyTorch is wanted on
this hardware, the driver needs updating first.

## Files

| File | Purpose |
|---|---|
| `intelligence/ml_service/nhanes_download.py` | Fetch and cache the public data |
| `intelligence/ml_service/nhanes_cohort.py` | Cohort derivation and the outcome definition |
| `intelligence/ml_service/train_nhanes.py` | Training, validation battery, model card |
| `intelligence/ml_service/evaluation.py` | Discrimination, calibration, subgroups, net benefit |
| `intelligence/ml_service/diagnostics.py` | Paired bootstrap comparison, coefficient stability |
| `intelligence/ml_service/gpu_arm.py` | Neural arm, ONNX export, OpenVINO GPU validation |
| `intelligence/ml_service/train.py` | The original synthetic generator, kept for the tests |
| `tests/integration/test_nhanes_model.py` | Sex is never guessed; the calibrator is applied correctly |
