"""The annotation specification is frozen, and these tests are the freeze.

Nothing here checks that the definitions are *good* - that is a judgement, and
it was made before collection started, which is the point. What these check is
that the definitions cannot move quietly:

* the recorded fingerprint still matches the definitions;
* the handbook annotators read still matches the definitions;
* every answer an annotator can give has a definition;
* annotations made under a different specification are refused, not pooled.

A mid-corpus definition change does not look like an error in the data. It
looks like annotator disagreement, or like a detector that performs worse on
the reports labelled later. By the time anyone suspects it, the corpus is
already mixed. So the guard has to be here, before the data exists.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import pytest

from intelligence.benchmark import spec
from intelligence.benchmark.extraction.schema import (
    DocumentAnnotation,
    ExtractionCorpus,
    FieldAnnotation,
)
from intelligence.benchmark.reasoning.schema import (
    ConditionSupport,
    Corpus,
    Determination,
    EvidenceSufficiency,
    ReportAnnotation,
)
from intelligence.document.contracts import ValueStatus

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestTheDefinitionsAreFrozen:
    def test_the_recorded_fingerprint_matches_the_definitions(self):
        # If this fails, a definition changed. That is allowed, but it is not
        # free: the failure message says what to do about the reports already
        # labelled under the previous wording.
        spec.check_frozen()

    def test_changing_a_definition_changes_the_fingerprint(self):
        before = spec.fingerprint()
        altered = tuple(
            dataclasses.replace(d, means=d.means + " Also, sometimes not.")
            if d.term == "AMBIGUOUS" else d
            for d in spec.DEFINITIONS
        )
        original = spec.DEFINITIONS
        try:
            spec.DEFINITIONS = altered  # type: ignore[misc]
            assert spec.fingerprint() != before
            with pytest.raises(AssertionError, match="have changed"):
                spec.check_frozen()
        finally:
            spec.DEFINITIONS = original  # type: ignore[misc]
        assert spec.fingerprint() == before

    def test_reordering_the_definitions_does_not(self):
        """The hash is over the meanings, not over the file layout."""
        before = spec.fingerprint()
        original = spec.DEFINITIONS
        try:
            spec.DEFINITIONS = tuple(reversed(original))  # type: ignore[misc]
            assert spec.fingerprint() == before
        finally:
            spec.DEFINITIONS = original  # type: ignore[misc]


class TestEveryAnswerIsDefined:
    """A new answer option must not reach an annotator undefined."""

    def test_every_value_status_has_a_definition(self):
        # The parser's own vocabulary. An annotator scoring extraction has to
        # be able to tell OBSERVED from AMBIGUOUS from NEEDS_REVIEW using the
        # same words the code uses, or the corpus measures something else.
        undefined = sorted(
            status.value for status in ValueStatus
            if status.value not in spec.DEFINITIONS_BY_TERM
        )
        assert not undefined, (
            f"{undefined} can be produced by the parser and asked of an "
            f"annotator, but is not defined in the annotation specification"
        )

    @pytest.mark.parametrize(
        "enum", [Determination, EvidenceSufficiency, ConditionSupport]
    )
    def test_every_clinical_answer_has_a_definition(self, enum):
        undefined = sorted(
            member.value for member in enum
            if member.value not in spec.DEFINITIONS_BY_TERM
        )
        assert not undefined, (
            f"{enum.__name__}: {undefined} is an answer a clinician can give "
            f"and the specification does not say what it means"
        )

    def test_the_terms_the_user_asked_to_freeze_are_frozen(self):
        for term in (
            "OBSERVED", "FABRICATION", "AMBIGUOUS", "NEEDS_REVIEW",
            "SUPPORTING_EVIDENCE", "MISSING_EVIDENCE", "ADJUDICATION",
        ):
            assert spec.definition(term).means

    def test_every_definition_says_who_decides_and_why(self):
        for d in spec.DEFINITIONS:
            assert d.why.strip(), f"{d.term}: no reason recorded"
            assert d.decided_by in (spec.ANNOTATOR, spec.CLINICIAN)

    def test_clinical_judgement_is_never_asked_of_a_transcriber(self):
        """Anything a clinician must decide belongs to the reasoning half."""
        for d in spec.DEFINITIONS:
            if d.decided_by == spec.CLINICIAN:
                assert d.layer == spec.REASONING, (
                    f"{d.term} needs clinical judgement but sits in the "
                    f"{d.layer} benchmark, which is annotated by transcribers"
                )

    def test_an_unknown_term_names_the_ones_that_exist(self):
        with pytest.raises(KeyError, match="OBSERVED"):
            spec.definition("PROBABLY_FINE")


class TestTheHandbookCannotDrift:
    def test_the_committed_handbook_is_what_the_definitions_generate(self):
        committed = (REPO_ROOT / spec.HANDBOOK_PATH).read_text(encoding="utf-8")
        assert committed == spec.handbook(), (
            "docs/annotation-spec.md is out of date. It is generated, not "
            "maintained: run `python -m intelligence.benchmark --write-handbook`"
        )

    def test_the_handbook_carries_the_version_and_fingerprint(self):
        text = (REPO_ROOT / spec.HANDBOOK_PATH).read_text(encoding="utf-8")
        assert spec.ANNOTATION_SPEC_VERSION in text
        assert spec.fingerprint() in text

    def test_the_handbook_shows_every_term_with_its_boundary(self):
        text = spec.handbook()
        for d in spec.DEFINITIONS:
            assert f"`{d.term}`" in text
            for example in d.does_not_count:
                # The negative examples are where annotation drifts, so they
                # are not an optional extra in the rendered document.
                assert example in text


class TestAnnotationsDeclareWhatTheyMeant:
    """A label is only comparable to another label made under the same words."""

    def _field(self) -> FieldAnnotation:
        return FieldAnnotation(
            analyte="hemoglobin", printed_label="Haemoglobin",
            value=13.4, unit="g/dL",
        )

    def test_an_extraction_annotation_defaults_to_the_current_specification(self):
        annotation = DocumentAnnotation(
            document_id="d1", annotator_id="a1", annotated_on=date(2026, 1, 1),
            document_type="CBC", fields=(self._field(),),
        )
        assert annotation.spec_version == spec.ANNOTATION_SPEC_VERSION

    def test_an_extraction_annotation_under_older_definitions_is_refused(self):
        with pytest.raises(ValueError, match="not pooled"):
            DocumentAnnotation(
                document_id="d1", annotator_id="a1",
                annotated_on=date(2026, 1, 1), document_type="CBC",
                fields=(self._field(),),
                spec_version="caresense-annotation-spec-0",
            )

    def test_a_reasoning_annotation_under_older_definitions_is_refused(self):
        with pytest.raises(ValueError, match="not pooled"):
            ReportAnnotation(
                report_id="r1", report_type="CBC", annotator_id="c1",
                annotated_on=date(2026, 1, 1),
                applicable_finding_codes=(), applicable_condition_codes=(),
                findings=(), conditions=(), human_review_required=False,
                spec_version="caresense-annotation-spec-0",
            )

    @pytest.mark.parametrize("corpus_class", [ExtractionCorpus, Corpus])
    def test_a_corpus_under_older_definitions_is_refused(self, corpus_class):
        with pytest.raises(ValueError, match="not pooled"):
            corpus_class(
                corpus_id="c", spec_version="caresense-annotation-spec-0"
            )
