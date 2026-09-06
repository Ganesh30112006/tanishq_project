"""What a cohort must provide before the validation harness will look at it.

The harness currently knows about two populations, both NHANES. When a genuine
Indian longitudinal cohort becomes available it has to go through *exactly the
same* pipeline, judged against *exactly the same* rules - otherwise the
comparison between what was shown in the US data and what is shown locally is
not a comparison at all.

So the rules live here rather than inside any one validation script:

* the columns a cohort must supply, and what each one means;
* the provenance a cohort must declare about itself;
* the horizon rule that decides whether calibration may be reported at all.

Adding a cohort is then a matter of writing a loader that returns a frame
satisfying :data:`CONTRACT`, declaring a :class:`CohortSpec`, and registering
the pair. Nothing in the judging changes, which is the point: a cohort cannot
be made to look better by being loaded differently.

Adding a cohort::

    from intelligence.ml_service.cohort_contract import CohortSpec, register

    SPEC = CohortSpec(
        key="my-cohort",
        label="...",
        provenance="who collected it, when, under what protocol",
        country="India",
        examined="2019-2021",
        outcome="cardiovascular death",
        outcome_source="how death and its cause were ascertained",
        horizon_months=120,
        ethnicity_scheme="how the group column is coded",
        role=EXTERNAL,
        consent_basis="the basis on which these records may be used",
    )

    def load() -> pd.DataFrame:
        ...

    register(SPEC, load)

Then ``python -m intelligence.ml_service.external_validation --cohort my-cohort``.

An unregistered cohort cannot be validated, and a registered one cannot skip
the contract check: :func:`validate_cohort` runs before any score is computed,
and a hard problem stops the run. A validation report produced from a frame
nobody checked is worth less than no report, because it looks the same as a
real one.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

# --- what a cohort is for -------------------------------------------------
DEVELOPMENT = "development"        #: the model was fitted on it
INTERNAL_TEST = "internal_test"    #: held out, but the same survey and protocol
EXTERNAL = "external"              #: never touched by fitting, calibration or selection

ROLES = (DEVELOPMENT, INTERNAL_TEST, EXTERNAL)


@dataclass(frozen=True)
class Column:
    name: str
    meaning: str
    #: A hard column is required to score anyone at all. A soft column is
    #: required to answer a *question* - subgroup reliability without an
    #: ethnicity column is not a weaker answer, it is no answer - so its
    #: absence is recorded as an unanswerable question rather than an error.
    hard: bool = True


#: Every cohort supplies these, whatever the model's features happen to be.
#: The model's own feature columns are checked separately, from its card, so
#: that this contract does not quietly hardcode one model's inputs.
CONTRACT: tuple[Column, ...] = (
    Column("y", "1 if the predicted outcome occurred within the horizon, else 0"),
    Column("age", "age in years at the point the features were measured"),
    Column("sex", "'Male' or 'Female' as recorded, never inferred", hard=False),
    Column("age_band", "banded age, for subgroup reporting", hard=False),
    Column(
        "ethnicity",
        "the group column used for subgroup and transportability reporting; "
        "its coding scheme must be declared in the spec, because comparing "
        "groups across differently-coded cohorts is the commonest way to make "
        "a false claim about who a model works for",
        hard=False,
    ),
)


@dataclass(frozen=True)
class CohortSpec:
    """What a cohort declares about itself, before anyone scores it."""

    key: str
    label: str
    provenance: str
    country: str
    examined: str
    outcome: str
    outcome_source: str
    horizon_months: int
    ethnicity_scheme: str
    role: str
    consent_basis: str
    #: Anything a reader must know to avoid over-reading the result. These are
    #: printed with the results, not buried in a footnote.
    caveats: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, got {self.role!r}")
        if self.horizon_months <= 0:
            raise ValueError("horizon_months must be positive")
        for name in ("label", "provenance", "outcome_source", "consent_basis"):
            if not getattr(self, name).strip():
                raise ValueError(f"a cohort must declare {name}")


# --- the horizon rule -----------------------------------------------------
def calibration_reportable(spec: CohortSpec, model_horizon_months: int):
    """May calibration be reported for this cohort, and if not, why not?

    This is the rule that stopped the NHANES 2011-2014 run from producing a
    calibration slope, and it lives here so that it applies to every cohort
    including ones written later. Discrimination is a statement about
    *ordering* and survives a horizon mismatch. Calibration is a statement
    about *level* and does not: comparing 10-year predictions against 5-year
    outcomes produces a slope that is wrong by construction and reads exactly
    like a finding.

    A longer follow-up than the model predicts is also refused, for the mirror
    reason.
    """
    if spec.horizon_months == model_horizon_months:
        return True, ""
    shorter = spec.horizon_months < model_horizon_months
    return False, (
        f"The model predicts risk over {model_horizon_months} months and this "
        f"cohort observes {spec.horizon_months}. A calibration statistic "
        f"comparing the two would be wrong by construction - predicted risk "
        f"would appear systematically "
        f"{'too high' if shorter else 'too low'} for reasons that have nothing "
        f"to do with the model - and would read as a finding. Only ordering is "
        f"reported."
    )


# --- checking a loaded frame ---------------------------------------------
@dataclass(frozen=True)
class Problem:
    severity: str      # "hard" stops the run; "soft" removes a question
    column: str
    message: str


def validate_cohort(df: pd.DataFrame, spec: CohortSpec, features) -> list[Problem]:
    """Check a loaded cohort against the contract and the model's inputs.

    Returns problems rather than raising, so that the caller can print all of
    them at once. A cohort with three missing columns should be told about
    three, not sent round the loop three times.
    """
    problems: list[Problem] = []

    for column in CONTRACT:
        if column.name not in df.columns:
            problems.append(Problem(
                "hard" if column.hard else "soft", column.name,
                f"missing: {column.meaning}",
            ))
    for name in features:
        if name not in df.columns:
            problems.append(Problem(
                "hard", name,
                "the model requires this feature and the cohort does not have it",
            ))

    if "y" in df.columns:
        values = set(pd.unique(df["y"].dropna()))
        # 0 == 0.0 == False in Python, so this set covers int, float and bool.
        if not values <= {0, 1}:
            problems.append(Problem(
                "hard", "y", f"outcome must be 0/1, found {sorted(map(str, values))[:6]}",
            ))
        elif df["y"].sum() == 0:
            problems.append(Problem(
                "hard", "y",
                "no events in this cohort - discrimination is undefined and any "
                "reported performance would be an artefact",
            ))
        elif df["y"].isna().any():
            problems.append(Problem(
                "hard", "y",
                f"{int(df['y'].isna().sum())} rows have no recorded outcome; a "
                "person with unknown follow-up is not a person who survived",
            ))

    if len(df) == 0:
        problems.append(Problem("hard", "-", "the cohort is empty"))

    return problems


def describe_problems(problems) -> str:
    if not problems:
        return "cohort satisfies the contract"
    lines = []
    for problem in sorted(problems, key=lambda p: (p.severity != "hard", p.column)):
        lines.append(f"  [{problem.severity:>4}] {problem.column}: {problem.message}")
    return "\n".join(lines)


# --- the registry ---------------------------------------------------------
_REGISTRY: dict[str, tuple[CohortSpec, Callable[[], pd.DataFrame]]] = {}


def register(spec: CohortSpec, loader: Callable[[], pd.DataFrame]) -> CohortSpec:
    if spec.key in _REGISTRY and _REGISTRY[spec.key][0] != spec:
        raise ValueError(
            f"cohort {spec.key!r} is already registered with a different "
            f"specification. A cohort key names a fixed population and a fixed "
            f"outcome definition; redefining one silently would make two "
            f"validation reports carrying the same name describe different data."
        )
    _REGISTRY[spec.key] = (spec, loader)
    return spec


def get(key: str):
    if key not in _REGISTRY:
        raise KeyError(
            f"unknown cohort {key!r}. Registered: {sorted(_REGISTRY) or 'none'}. "
            f"A cohort must be registered with a declared provenance before it "
            f"can be validated against."
        )
    return _REGISTRY[key]


def registered() -> list[str]:
    return sorted(_REGISTRY)
