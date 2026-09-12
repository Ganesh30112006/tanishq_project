"""Numbers the system reasons with, and what stands behind each of them.

The reference intervals and the variation thresholds are not measurements this
system made. They come from textbooks, guidelines and the literature on assay
variation - good sources, none of which is a statement about the laboratories
whose reports CareSense actually reads.

Left unmarked they quietly acquire the authority of the system that uses them.
A trend reported because a change exceeded a literature threshold reads exactly
like a trend CareSense measured, and nothing downstream can tell the two apart.
So the provenance is carried in code rather than in a docstring, and these
tests stop it being quietly promoted.
"""
from __future__ import annotations

import pytest

from intelligence.knowledge import reference_ranges as RR
from intelligence.knowledge import variation as VAR
from intelligence.knowledge.provenance import (
    Applicability,
    Provenance,
    SourceType,
    ValidationStatus,
)

TABLES = [
    pytest.param(VAR.PROVENANCE, id="variation-thresholds"),
    pytest.param(RR.PROVENANCE, id="reference-ranges"),
]


@pytest.mark.parametrize("provenance", TABLES)
def test_no_table_claims_to_have_been_measured_here(provenance):
    assert provenance.source_type is not SourceType.MEASURED_HERE
    assert provenance.validation_status is ValidationStatus.NOT_VALIDATED
    assert provenance.applicability is Applicability.UNKNOWN
    assert not provenance.measured_here


@pytest.mark.parametrize("provenance", TABLES)
def test_every_table_says_what_would_validate_it(provenance):
    """So "not validated" does not become a permanent shrug."""
    assert provenance.what_would_validate_it.strip()
    assert provenance.source.strip()


@pytest.mark.parametrize("provenance", TABLES)
def test_every_table_produces_a_caveat_a_result_can_carry(provenance):
    caveat = provenance.caveat()
    assert "not been measured" in caveat
    assert provenance.source in caveat


def test_the_variation_table_says_the_benchmark_cannot_settle_it():
    """The gold-standard corpus answers whether a rule finds what a clinician
    would find. It contains no repeated measurements of one patient on one
    assay, so it cannot answer what that assay's variation is - and treating
    an empty benchmark as the pending validation for this would be a fake
    validation mechanism."""
    said = VAR.PROVENANCE.what_would_validate_it.lower()
    assert "benchmark cannot answer this" in said
    assert "repeated measurements" in said


def test_the_range_table_says_the_laboratory_range_is_preferred():
    assert "own printed range is preferred" in RR.PROVENANCE.what_would_validate_it


# --- the record refuses to be empty or self-contradictory ------------
def test_an_unvalidated_figure_must_say_what_would_validate_it():
    with pytest.raises(ValueError, match="permanent shrug"):
        Provenance(
            source_type=SourceType.LITERATURE,
            source="a paper",
            validation_status=ValidationStatus.NOT_VALIDATED,
        )


def test_a_figure_measured_here_cannot_also_be_unvalidated():
    with pytest.raises(ValueError, match="one of the two fields is wrong"):
        Provenance(
            source_type=SourceType.MEASURED_HERE,
            source="our own data",
            what_would_validate_it="nothing, it is measured",
        )


def test_a_provenance_record_must_name_its_source():
    with pytest.raises(ValueError, match="must name its source"):
        Provenance(source_type=SourceType.LITERATURE, source="  ",
                   what_would_validate_it="x")


def test_a_measured_figure_carries_no_caveat():
    measured = Provenance(
        source_type=SourceType.MEASURED_HERE,
        source="repeated measurements from the connected laboratories",
        applicability=Applicability.ESTABLISHED,
        validation_status=ValidationStatus.VALIDATED_HERE,
    )
    assert measured.caveat() == ""
    assert measured.measured_here


# --- and every trend built on a threshold inherits it ----------------
def test_a_trend_carries_the_provenance_of_the_threshold_that_decided_it():
    from datetime import date, timedelta

    from intelligence.document.contracts import ReferenceStatus
    from intelligence.findings.history import Observation, build_series

    start = date(2025, 1, 6)
    series = build_series("egfr", [
        Observation(analyte="egfr", value=value, unit="mL/min/1.73m2",
                    observed_on=start + timedelta(days=i * 120),
                    status=ReferenceStatus.BELOW, report_id=f"r-{i}",
                    reference_low=60.0)
        for i, value in enumerate([52.0, 49.0, 46.0])
    ])

    assert series.variation_provenance is VAR.PROVENANCE
    assert any(VAR.PROVENANCE.caveat() == c for c in series.caveats), (
        "a trend must carry the caveat of the threshold that produced it"
    )
