"""The annotation schema, and what it refuses to load.

Every check in the schema exists because the alternative is a corpus that
loads, scores, and produces a number that is wrong in a direction nobody can
see. A half-answered report drops a code out of the denominator; a report read
twice by one person looks like agreement; an adjudication with no reason
throws away the most useful text in the corpus.

The fixtures here are built in memory. There is deliberately no annotated
corpus in this repository, and a manufactured one would be indistinguishable
from real clinician data a few months from now.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from intelligence.benchmark import (
    ANNOTATION_SCHEMA_VERSION,
    Adjudication,
    BenchmarkItem,
    ConditionAnnotation,
    ConditionSupport,
    Corpus,
    CorpusError,
    Determination,
    EvidenceSufficiency,
    FindingAnnotation,
    LabelSource,
    ReportAnnotation,
    condition_label,
    disagreements,
    finding_label,
    integrity_problems,
    load,
)

TODAY = date(2026, 2, 11)


def _finding(code="ANEMIA_PATTERN", determination=Determination.PRESENT,
             sufficient=EvidenceSufficiency.SUFFICIENT) -> FindingAnnotation:
    return FindingAnnotation(
        code=code, determination=determination, evidence_sufficient=sufficient
    )


def _annotation(annotator="clinician-1", *, findings=None, conditions=None,
                review=True, report_id="r-1") -> ReportAnnotation:
    findings = tuple(findings if findings is not None else (_finding(),))
    conditions = tuple(conditions or ())
    return ReportAnnotation(
        report_id=report_id,
        report_type="CBC",
        annotator_id=annotator,
        annotated_on=TODAY,
        applicable_finding_codes=tuple(f.code for f in findings),
        applicable_condition_codes=tuple(c.code for c in conditions),
        findings=findings,
        conditions=conditions,
        human_review_required=review,
    )


def _item(*annotations, adjudication=None, report_id="r-1") -> BenchmarkItem:
    return BenchmarkItem(
        report_id=report_id,
        report_type="CBC",
        source_sha256="a" * 64,
        annotations=tuple(annotations or (_annotation(),)),
        adjudication=adjudication,
    )


# --- an annotation must answer what it scoped -----------------------
def test_a_declared_code_that_is_not_answered_is_refused():
    """It would silently leave the denominator and skew the recall."""
    with pytest.raises(ValueError, match="did not answer them"):
        ReportAnnotation(
            report_id="r-1", report_type="CBC", annotator_id="c1",
            annotated_on=TODAY,
            applicable_finding_codes=("ANEMIA_PATTERN", "MICROCYTOSIS_PATTERN"),
            applicable_condition_codes=(),
            findings=(_finding("ANEMIA_PATTERN"),),
            conditions=(),
            human_review_required=True,
        )


def test_an_answer_for_a_code_that_was_not_scoped_is_refused():
    with pytest.raises(ValueError, match="not declared applicable"):
        ReportAnnotation(
            report_id="r-1", report_type="CBC", annotator_id="c1",
            annotated_on=TODAY,
            applicable_finding_codes=("ANEMIA_PATTERN",),
            applicable_condition_codes=(),
            findings=(_finding("ANEMIA_PATTERN"), _finding("MICROCYTOSIS_PATTERN")),
            conditions=(),
            human_review_required=True,
        )


def test_the_same_code_answered_twice_is_refused():
    with pytest.raises(ValueError, match="answered twice"):
        ReportAnnotation(
            report_id="r-1", report_type="CBC", annotator_id="c1",
            annotated_on=TODAY,
            applicable_finding_codes=("ANEMIA_PATTERN",),
            applicable_condition_codes=(),
            findings=(_finding(), _finding(determination=Determination.ABSENT)),
            conditions=(),
            human_review_required=True,
        )


def test_undecidable_and_sufficient_at_once_is_refused():
    with pytest.raises(ValueError, match="cannot be sufficient"):
        _finding(determination=Determination.CANNOT_DETERMINE,
                 sufficient=EvidenceSufficiency.SUFFICIENT)


def test_an_annotation_from_an_older_question_set_is_not_pooled():
    with pytest.raises(ValueError, match="different question sets"):
        ReportAnnotation(
            report_id="r-1", report_type="CBC", annotator_id="c1",
            annotated_on=TODAY, applicable_finding_codes=(),
            applicable_condition_codes=(), findings=(), conditions=(),
            human_review_required=True, schema_version="benchmark-annotation-0",
        )


# --- an item must be two independent reads --------------------------
def test_the_same_annotator_twice_is_one_read_not_two():
    with pytest.raises(ValueError, match="appears twice"):
        _item(_annotation("clinician-1"), _annotation("clinician-1"))


def test_an_item_carrying_someone_elses_annotation_is_refused():
    with pytest.raises(ValueError, match="carries an annotation for"):
        _item(_annotation(report_id="r-2"), report_id="r-1")


def test_a_single_reader_loads_but_is_reported_as_a_weakness():
    corpus = Corpus(corpus_id="c", items=[_item(_annotation("clinician-1"))])
    problems = integrity_problems(corpus)
    assert any("read by 1 clinician" in p for p in problems)


def test_a_duplicate_report_id_in_a_corpus_is_refused():
    with pytest.raises(ValueError, match="appears twice"):
        Corpus(corpus_id="c", items=[_item(), _item()])


# --- an adjudication must say why -----------------------------------
def test_an_adjudication_without_a_reason_is_refused():
    """The reason is where the cases the rules get wrong describe themselves."""
    with pytest.raises(ValueError, match="why the annotators disagreed"):
        Adjudication(
            adjudicator_id="clinician-3", adjudicated_on=TODAY,
            findings=(_finding(),), disagreement_reason="  ",
        )


def test_an_adjudication_that_rules_on_nothing_is_refused():
    with pytest.raises(ValueError, match="rules on nothing"):
        Adjudication(
            adjudicator_id="clinician-3", adjudicated_on=TODAY,
            disagreement_reason="they read the printed range differently",
        )


# --- resolving several answers into one label -----------------------
def test_agreement_gives_a_unanimous_label():
    item = _item(_annotation("c1"), _annotation("c2"))
    label = finding_label(item, "ANEMIA_PATTERN")
    assert label.source is LabelSource.UNANIMOUS
    assert label.determination is Determination.PRESENT
    assert label.scoreable


def test_disagreement_without_a_ruling_is_not_scoreable():
    """Taking a majority would turn measured disagreement into invisible
    agreement, and the disagreement is itself a measurement."""
    item = _item(
        _annotation("c1"),
        _annotation("c2", findings=(_finding(determination=Determination.ABSENT),)),
    )
    label = finding_label(item, "ANEMIA_PATTERN")
    assert label.source is LabelSource.UNRESOLVED
    assert label.determination is None
    assert not label.scoreable
    assert set(label.answers) == {"PRESENT", "ABSENT"}


def test_a_ruling_settles_a_disagreement():
    item = _item(
        _annotation("c1"),
        _annotation("c2", findings=(_finding(determination=Determination.ABSENT),)),
        adjudication=Adjudication(
            adjudicator_id="c3", adjudicated_on=TODAY,
            findings=(_finding(determination=Determination.ABSENT),),
            disagreement_reason=(
                "the printed range was for a paediatric population"
            ),
        ),
    )
    label = finding_label(item, "ANEMIA_PATTERN")
    assert label.source is LabelSource.ADJUDICATED
    assert label.determination is Determination.ABSENT
    assert label.scoreable


def test_a_code_nobody_scoped_is_not_applicable_rather_than_absent():
    item = _item(_annotation("c1"), _annotation("c2"))
    label = finding_label(item, "TSH_ELEVATION_PATTERN")
    assert label.source is LabelSource.NOT_APPLICABLE
    assert not label.scoreable


def test_a_condition_resolves_the_same_way():
    supported = ConditionAnnotation(
        code="POSSIBLE_IRON_DEFICIENCY_ANEMIA", support=ConditionSupport.SUPPORTED
    )
    insufficient = ConditionAnnotation(
        code="POSSIBLE_IRON_DEFICIENCY_ANEMIA",
        support=ConditionSupport.INSUFFICIENT,
    )
    agreed = _item(
        _annotation("c1", conditions=(supported,)),
        _annotation("c2", conditions=(supported,)),
    )
    assert condition_label(
        agreed, "POSSIBLE_IRON_DEFICIENCY_ANEMIA"
    ).support is ConditionSupport.SUPPORTED

    split = _item(
        _annotation("c1", conditions=(supported,)),
        _annotation("c2", conditions=(insufficient,)),
    )
    assert condition_label(
        split, "POSSIBLE_IRON_DEFICIENCY_ANEMIA"
    ).source is LabelSource.UNRESOLVED


def test_disagreements_are_reported_with_what_each_reader_said():
    item = _item(
        _annotation("c1"),
        _annotation("c2", findings=(_finding(determination=Determination.ABSENT),)),
    )
    found = disagreements(item)
    assert set(found["ANEMIA_PATTERN"]) == {"PRESENT", "ABSENT"}


# --- loading a file -------------------------------------------------
def _corpus_json(**over) -> dict:
    annotation = {
        "report_id": "r-1", "report_type": "CBC", "annotator_id": "c1",
        "annotated_on": "2026-02-11",
        "applicable_finding_codes": ["ANEMIA_PATTERN"],
        "applicable_condition_codes": [],
        "findings": [{
            "code": "ANEMIA_PATTERN", "determination": "PRESENT",
            "evidence_sufficient": "SUFFICIENT",
        }],
        "conditions": [],
        "human_review_required": True,
    }
    return {
        "corpus_id": "test-corpus",
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "items": [{
            "report_id": "r-1", "report_type": "CBC", "source_sha256": "a" * 64,
            "annotations": [annotation, {**annotation, "annotator_id": "c2"}],
        }],
        **over,
    }


def _write(tmp_path, payload) -> str:
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_a_well_formed_corpus_loads(tmp_path):
    corpus = load(_write(tmp_path, _corpus_json()))
    assert len(corpus) == 1
    assert corpus.items[0].annotator_count == 2
    assert integrity_problems(corpus) == []


def test_a_corpus_from_another_question_set_is_refused(tmp_path):
    payload = _corpus_json(schema_version="benchmark-annotation-0")
    with pytest.raises(CorpusError, match="this code speaks"):
        load(_write(tmp_path, payload))


def test_an_unknown_determination_is_refused_rather_than_dropped(tmp_path):
    payload = _corpus_json()
    payload["items"][0]["annotations"][0]["findings"][0]["determination"] = "MAYBE"
    with pytest.raises(CorpusError, match="bad finding annotation"):
        load(_write(tmp_path, payload))


def test_a_bad_date_is_refused(tmp_path):
    payload = _corpus_json()
    payload["items"][0]["annotations"][0]["annotated_on"] = "last Tuesday"
    with pytest.raises(CorpusError, match="not an ISO date"):
        load(_write(tmp_path, payload))


def test_a_missing_file_is_a_corpus_error_not_a_crash(tmp_path):
    with pytest.raises(CorpusError):
        load(tmp_path / "nothing-here.json")


def test_a_report_with_no_scoped_codes_contributes_nothing_and_says_so():
    corpus = Corpus(corpus_id="c", items=[
        BenchmarkItem(
            report_id="r-9", report_type="RADIOLOGY", source_sha256="b" * 64,
            annotations=(
                ReportAnnotation(
                    report_id="r-9", report_type="RADIOLOGY", annotator_id="c1",
                    annotated_on=TODAY, applicable_finding_codes=(),
                    applicable_condition_codes=(), findings=(), conditions=(),
                    human_review_required=True,
                ),
                ReportAnnotation(
                    report_id="r-9", report_type="RADIOLOGY", annotator_id="c2",
                    annotated_on=TODAY, applicable_finding_codes=(),
                    applicable_condition_codes=(), findings=(), conditions=(),
                    human_review_required=True,
                ),
            ),
        )
    ])
    assert any("contributes nothing" in p for p in integrity_problems(corpus))
