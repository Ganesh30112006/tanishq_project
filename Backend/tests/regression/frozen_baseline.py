"""The frozen clinical baseline.

Everything in this file is a pinned fact about the cardiovascular pathway as it
stood when document-intelligence work began. It is data, not logic, so that a
change to the clinical engine shows up as a diff to these constants and has to
be argued for, rather than being absorbed silently by a test that recomputes
whatever the code currently does.

A test that derives its expectation from the code under test proves only that
the code is self-consistent. The scores below were produced by scoring the
shipped artifact through the real inference endpoint and writing the answers
down. If they change, either the model changed, the calibration changed, or a
numerical dependency moved underneath it - and all three are things somebody
needs to know about before a patient is scored.

Nothing here is a claim that the numbers are *right*. They are a claim that
they are *the same ones*, which is a different and more checkable thing.
"""
from __future__ import annotations

MODEL_ID = "cvd-nhanes-logreg"
MODEL_VERSION = "3.1.0"
FEATURE_SCHEMA_VERSION = "fs-3.1.0"
PREPROCESSING_VERSION = "pp-nhanes-1"
CALIBRATION_VERSION = "cal-3.1.0-none"
EXPLANATION_VERSION = "linear-shap-1"

#: Order matters: the estimator consumes a positional array.
FEATURE_ORDER = ["age", "is_male", "systolic_bp", "current_smoker"]

#: The range the model was fitted on. Outside it the system refuses rather than
#: extrapolating, and the refusal wording depends on which side was crossed.
VALIDATED_DOMAIN = {
    "age": {"min": 40.0, "max": 79.0},
    "is_male": {"min": 0.0, "max": 1.0},
    "systolic_bp": {"min": 94.0, "max": 193.3333},
    "current_smoker": {"min": 0.0, "max": 1.0},
}

#: Sign of the standardised coefficient for each feature. This drives the
#: directional refusal: a blood pressure above the ceiling and one below the
#: floor are both out of domain, but only one is the record's most alarming
#: number.
RISK_DIRECTION = {"age": 1, "is_male": 1, "systolic_bp": 1, "current_smoker": 1}

#: Floating-point work is not bit-identical across every BLAS build, so the
#: comparison is to twelve decimal places rather than to the last bit. A drift
#: larger than this is not rounding - it is a different model.
SCORE_TOLERANCE = 1e-12

#: Scored through /v1/infer against cvd-3.1.0.joblib. The calibrator selected
#: for 3.1.0 was "none", so the raw and calibrated scores coincide; that is
#: itself part of the frozen surface, and a divergence here would mean a
#: calibrator appeared where none was chosen.
GOLDEN_VECTORS = [
    {
        "label": "typical man, treated blood pressure, never smoked",
        "features": {"age": 62.0, "is_male": 1.0, "systolic_bp": 138.0,
                     "current_smoker": 0.0},
        "raw_score": 0.050547925254245764,
        "calibrated_score": 0.050547925254245764,
        "reliability": "VALID",
    },
    {
        "label": "the same record with sex flipped",
        "features": {"age": 62.0, "is_male": 0.0, "systolic_bp": 138.0,
                     "current_smoker": 0.0},
        "raw_score": 0.029904364669580293,
        "calibrated_score": 0.029904364669580293,
        "reliability": "VALID",
    },
    {
        "label": "youngest in domain, low risk",
        "features": {"age": 40.0, "is_male": 0.0, "systolic_bp": 110.0,
                     "current_smoker": 0.0},
        "raw_score": 0.0033223693930812415,
        "calibrated_score": 0.0033223693930812415,
        "reliability": "VALID",
    },
    {
        "label": "oldest, hypertensive, smoking",
        "features": {"age": 79.0, "is_male": 1.0, "systolic_bp": 180.0,
                     "current_smoker": 1.0},
        "raw_score": 0.43974128502871895,
        "calibrated_score": 0.43974128502871895,
        "reliability": "VALID",
    },
    {
        "label": "exactly on the domain floor",
        "features": {"age": 40.0, "is_male": 0.0, "systolic_bp": 94.0,
                     "current_smoker": 0.0},
        "raw_score": 0.002772636485810125,
        "calibrated_score": 0.002772636485810125,
        "reliability": "VALID",
    },
    {
        "label": "exactly on the domain ceiling",
        "features": {"age": 79.0, "is_male": 1.0, "systolic_bp": 193.3333,
                     "current_smoker": 1.0},
        "raw_score": 0.47726069053605824,
        "calibrated_score": 0.47726069053605824,
        "reliability": "VALID",
    },
    {
        "label": "middle-aged smoker at a normal pressure",
        "features": {"age": 55.0, "is_male": 1.0, "systolic_bp": 120.0,
                     "current_smoker": 1.0},
        "raw_score": 0.047300286917688006,
        "calibrated_score": 0.047300286917688006,
        "reliability": "VALID",
    },
]

#: The evidence framework's own frozen surface. A model may not be asked easier
#: questions than an earlier one, and the bar for "transport is established"
#: may not be quietly relaxed.
QUESTIONS_VERSION = "evidence-questions-1"
CRITERIA_VERSION = "cvd-acceptance-1"
DECISION_THRESHOLD = 0.05
MEANINGFUL_AUC_DROP = 0.05

QUESTION_KEYS = [
    "development_population", "validation_populations", "representation",
    "exclusions", "abstention_rate", "abstention_reasons", "discrimination",
    "calibration", "subgroup_variation", "transportability", "missing_evidence",
]

#: What 3.1.0's dossier says today. If document intelligence ever changes one
#: of these, something has reached across a boundary it should not have.
DOSSIER_STATUS_COUNTS = {"answered": 7, "partial": 3, "unanswered": 1}
OPEN_EVIDENCE_QUESTIONS = [
    "representation", "exclusions", "calibration", "transportability",
]
