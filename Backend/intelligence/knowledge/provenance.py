"""Where a number in the knowledge layer came from, and what stands behind it.

The reference ranges, the variation thresholds and the decision boundaries in
this package are all *numbers the system reasons with*, and none of them was
measured here. They come from textbooks, from published guidelines and from
the literature on assay variation - each of which is a perfectly good source,
and none of which is a statement about the laboratories whose reports CareSense
actually processes.

Left unmarked, those numbers quietly acquire the authority of the system that
uses them. A trend reported because a change exceeded a literature threshold
reads exactly like a trend CareSense measured, and nobody downstream can tell
the difference. So every such number carries this, and every result built on
one says so.

This is the same discipline as ``DetectorValidation`` one layer down: a figure
from a paper is a hypothesis about this system's data until somebody measures
it here, and the honest thing is to say which it is rather than to round up.

**The empty benchmark is not a way out of this.** The gold-standard corpus
answers "does this rule identify the finding a clinician would identify?" It
cannot answer "is this the right analytical variation for this laboratory's
instrument", because it does not contain repeated measurements on the same
patient from the same assay. Marking these NOT_VALIDATED is not a placeholder
waiting for the benchmark; it is waiting for a different study.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceType(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    #: A published paper, textbook or reference work.
    LITERATURE = "LITERATURE"
    #: A clinical practice guideline - a number chosen because acting on it
    #: changes outcomes, rather than because it describes a population.
    GUIDELINE = "GUIDELINE"
    #: Printed by the laboratory that ran the assay, for that instrument.
    LABORATORY = "LABORATORY"
    #: Measured on this system's own data.
    MEASURED_HERE = "MEASURED_HERE"


class Applicability(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    #: Nobody has checked whether this figure applies to the population and
    #: the assays this system sees. The honest default.
    UNKNOWN = "UNKNOWN"
    #: Checked and found to apply.
    ESTABLISHED = "ESTABLISHED"
    #: Checked and found not to apply, or to apply only in part.
    LIMITED = "LIMITED"


class ValidationStatus(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    NOT_VALIDATED = "NOT_VALIDATED"
    VALIDATED_HERE = "VALIDATED_HERE"


@dataclass(frozen=True, slots=True)
class Provenance:
    """What stands behind one number in the knowledge layer."""

    source_type: SourceType
    source: str
    applicability: Applicability = Applicability.UNKNOWN
    validation_status: ValidationStatus = ValidationStatus.NOT_VALIDATED
    #: What would have to be done to move this to MEASURED_HERE. Naming it
    #: keeps "not validated" from becoming a permanent shrug.
    what_would_validate_it: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("a provenance record must name its source")
        if (
            self.validation_status is ValidationStatus.NOT_VALIDATED
            and not self.what_would_validate_it.strip()
        ):
            raise ValueError(
                f"{self.source!r}: an unvalidated figure must say what would "
                f"validate it, so 'not validated' does not become a permanent "
                f"shrug"
            )
        if (
            self.source_type is SourceType.MEASURED_HERE
            and self.validation_status is ValidationStatus.NOT_VALIDATED
        ):
            raise ValueError(
                f"{self.source!r}: a figure measured here is validated here by "
                f"definition - one of the two fields is wrong"
            )

    @property
    def measured_here(self) -> bool:
        return self.source_type is SourceType.MEASURED_HERE

    def caveat(self) -> str:
        """The sentence a result built on this number has to carry."""
        if self.measured_here:
            return ""
        return (
            f"This uses a {self.source_type.value.lower()} figure ({self.source}). "
            f"It has not been measured on the laboratories this system reads, "
            f"and how well it applies to them is {self.applicability.value.lower()}."
        )
