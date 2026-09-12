"""Measuring the reading layer on its own.

The reason this exists as a separate benchmark, in one sentence: a detector
can reason flawlessly on a misread haemoglobin, and perfect extraction can
feed an unsafe rule. Scored together those two failures are indistinguishable,
and the number they produce tells nobody which layer to fix.

Within it, the number that matters is not precision. It is **fabrication**: a
value the parser persisted that the report does not print. A missed result is
a gap a person can see; a wrong result is one nobody can. They are counted
separately and never added together, and the fabrication gate is the one place
in either benchmark that is a correctness bar rather than a size-of-measurement
one.

Fixtures are built in memory. No annotated corpus is committed to this
repository and none may be manufactured.
"""
from __future__ import annotations

from datetime import date

import pytest

from intelligence.benchmark.extraction import (
    DocumentAnnotation,
    ExtractionAdjudication,
    ExtractionCorpus,
    ExtractionItem,
    FieldAnnotation,
    SystemValue,
    integrity_problems,
    score,
)
from intelligence.benchmark.promotion import (
    MIN_EXTRACTED_FIELDS,
    MIN_EXTRACTION_DOCUMENTS,
    MIN_REFUSABLE_LINES,
    evaluate_extraction,
)

TODAY = date(2026, 2, 11)


def _field(analyte="hemoglobin", label="Hemoglobin", value=13.4, unit="g/dL",
           ref="13.0 - 17.0", flag="", section="COMPLETE BLOOD COUNT",
           refusable=False, why_not=""):
    return FieldAnnotation(
        analyte=analyte, printed_label=label, value=value, unit=unit,
        reference_text=ref, printed_flag=flag, section=section,
        should_not_be_extracted=refusable, why_not=why_not,
    )


def _page_number():
    return FieldAnnotation(
        analyte="", printed_label="Page 1 of 3", should_not_be_extracted=True,
        why_not="page furniture, not a result",
    )


def _annotation(annotator="a1", document_id="d-1", fields=None,
                doc_type="CBC", readable=True):
    return DocumentAnnotation(
        document_id=document_id, annotator_id=annotator, annotated_on=TODAY,
        document_type=doc_type,
        fields=tuple(fields if fields is not None else (_field(), _page_number())),
        readable=readable,
    )


def _item(document_id="d-1", fields=None, second_fields=None, adjudication=None):
    annotations = [_annotation("a1", document_id, fields)]
    annotations.append(
        _annotation("a2", document_id, second_fields if second_fields is not None
                    else fields)
    )
    return ExtractionItem(
        document_id=document_id, source_sha256="a" * 64,
        annotations=tuple(annotations), adjudication=adjudication,
    )


def _corpus(*items):
    return ExtractionCorpus(corpus_id="extraction-test", items=list(items))


def _system(analyte="hemoglobin", label="Hemoglobin", value=13.4, unit="g/dL",
            ref="13.0 - 17.0", flag="", section="COMPLETE BLOOD COUNT",
            persists=True, status="OBSERVED", reason=""):
    return SystemValue(
        analyte=analyte, printed_label=label, value=value, unit=unit,
        reference_text=ref, printed_flag=flag, section=section,
        persists_clinical_value=persists, status=status, reason=reason,
    )


# --- the schema refuses what it cannot mean -------------------------
def test_a_line_that_yields_nothing_must_say_why():
    """That reason is what the parser is being asked to reproduce."""
    with pytest.raises(ValueError, match="must say why"):
        FieldAnnotation(
            analyte="", printed_label="Page 1 of 3", should_not_be_extracted=True
        )


def test_a_line_that_yields_nothing_cannot_carry_a_value():
    with pytest.raises(ValueError, match="carries a value"):
        FieldAnnotation(
            analyte="", printed_label="Page 1 of 3", value=1.0,
            should_not_be_extracted=True, why_not="furniture",
        )


def test_an_analyte_with_no_value_must_declare_which_it_is():
    with pytest.raises(ValueError, match="Which is it"):
        FieldAnnotation(analyte="hemoglobin", printed_label="Hemoglobin")


def test_an_unreadable_document_cannot_also_carry_fields():
    with pytest.raises(ValueError, match="marked unreadable but carries fields"):
        _annotation(fields=(_field(),), readable=False)


def test_the_same_annotator_twice_is_one_read_not_two():
    with pytest.raises(ValueError, match="appears twice"):
        ExtractionItem(
            document_id="d-1", source_sha256="a" * 64,
            annotations=(_annotation("a1"), _annotation("a1")),
        )


def test_an_adjudication_must_say_why_the_annotators_differed():
    """Two people reading the same printed number differently is the most
    useful signal this corpus produces."""
    with pytest.raises(ValueError, match="record why the annotators differed"):
        ExtractionAdjudication(
            adjudicator_id="a3", adjudicated_on=TODAY, fields=(_field(),),
        )


def test_a_corpus_without_refusable_lines_is_reported_as_a_weakness():
    """Most of a report is not a result, and a corpus that records only the
    results cannot measure whether the parser invents any."""
    corpus = _corpus(_item(fields=(_field(),)))
    assert any("no line is marked as yielding nothing" in p
               for p in integrity_problems(corpus))


# --- detection ------------------------------------------------------
def test_a_correctly_read_line_is_found():
    result = score(_corpus(_item()), {"d-1": [_system()]})
    assert result.found == 1
    assert result.missed == 0
    assert result.invented == 0
    assert result.detection_recall == 1.0


def test_a_line_the_parser_did_not_produce_is_missed():
    result = score(_corpus(_item()), {"d-1": []})
    assert result.missed == 1
    assert result.detection_recall == 0.0
    assert result.fabrications == 0, "a miss is not a fabrication"


def test_a_line_no_annotator_recorded_is_invented():
    result = score(
        _corpus(_item()),
        {"d-1": [_system(), _system(analyte="tsh", label="TSH", value=2.1,
                                    unit="uIU/mL", ref="0.4 - 4.0")]},
    )
    assert result.invented == 1
    assert result.detection_precision == 0.5


# --- transcription, attribute by attribute --------------------------
def test_each_attribute_is_scored_on_its_own():
    """A parser that reads every number right and every unit wrong is a
    different problem from one that does the reverse."""
    result = score(_corpus(_item()), {"d-1": [_system(unit="mg/dL")]})
    assert result.attributes["value"].correct == 1
    assert result.attributes["unit"].wrong == 1
    assert result.attributes["unit"].accuracy == 0.0
    assert result.attributes["value"].accuracy == 1.0


@pytest.mark.parametrize("attribute,wrong", [
    ("unit", {"unit": "mg/dL"}),
    ("reference_text", {"ref": "12.0 - 16.0"}),
    ("printed_flag", {"flag": "H"}),
    ("section", {"section": "CHEMISTRY"}),
])
def test_a_wrong_attribute_is_counted_against_that_attribute(attribute, wrong):
    result = score(_corpus(_item()), {"d-1": [_system(**wrong)]})
    assert result.attributes[attribute].wrong == 1
    assert result.attributes["value"].correct == 1


def test_whitespace_and_case_do_not_count_as_a_transcription_error():
    result = score(
        _corpus(_item()),
        {"d-1": [_system(ref="13.0  -  17.0", section="complete blood count")]},
    )
    assert result.attributes["reference_text"].correct == 1
    assert result.attributes["section"].correct == 1


# --- fabrication, the headline --------------------------------------
def test_a_wrong_value_that_was_persisted_is_a_fabrication():
    """The number that matters: a missed result is a gap a person can see, a
    wrong one is a gap nobody can."""
    result = score(_corpus(_item()), {"d-1": [_system(value=1.0)]})
    assert result.wrong_value_persisted == 1
    assert result.fabrications == 1
    assert any("persisted 1.0 where the report prints 13.4" in e
               for e in result.examples_of_fabrication)


def test_a_value_persisted_for_a_line_that_yields_nothing_is_a_fabrication():
    result = score(
        _corpus(_item()),
        {"d-1": [_system(), _system(analyte="", label="Page 1 of 3", value=1.0,
                                    unit="", ref="", section="")]},
    )
    assert result.persisted_a_refusable_line == 1
    assert result.fabrications == 1


def test_refusing_out_loud_is_never_a_fabrication():
    """Refusing is what the whole status ladder exists to produce. Counting it
    as an error would push the system towards confident guesses."""
    result = score(
        _corpus(_item()),
        {"d-1": [_system(value=1.0, persists=False, status="AMBIGUOUS",
                         reason="more_than_one_number_on_the_line")]},
    )
    assert result.fabrications == 0
    assert result.refused_out_loud == 1


def test_the_fabrication_rate_is_over_what_was_persisted():
    two_fields = (_field(), _field(analyte="wbc", label="WBC", value=7.2,
                                   unit="10^9/L", ref="4.0 - 11.0"),
                  _page_number())
    result = score(
        _corpus(_item(fields=two_fields)),
        {"d-1": [_system(value=1.0),
                 _system(analyte="wbc", label="WBC", value=7.2, unit="10^9/L",
                         ref="4.0 - 11.0")]},
    )
    assert result.fabrications == 1
    assert result.fabrication_rate == pytest.approx(0.5)


# --- refusal --------------------------------------------------------
def test_correctly_yielding_nothing_is_counted():
    result = score(_corpus(_item()), {"d-1": [_system()]})
    assert result.refusable_lines == 1
    assert result.correctly_refused == 1
    assert result.refusal_rate == 1.0


def test_producing_a_refusable_line_but_refusing_it_counts_as_refused():
    result = score(
        _corpus(_item()),
        {"d-1": [_system(),
                 _system(analyte="", label="Page 1 of 3", value=1.0, unit="",
                         ref="", section="", persists=False,
                         status="AMBIGUOUS", reason="unrecognised_analyte")]},
    )
    assert result.correctly_refused == 1
    assert result.fabrications == 0


# --- disagreement ---------------------------------------------------
def test_two_annotators_transcribing_differently_is_not_scoreable():
    item = _item(
        fields=(_field(), _page_number()),
        second_fields=(_field(value=13.5), _page_number()),
    )
    result = score(_corpus(item), {"d-1": [_system()]})
    assert result.found == 0
    assert result.attributes["value"].unresolved == 1
    assert result.unresolved_rate == 1.0


def test_an_adjudicated_transcription_is_scored_against_the_ruling():
    item = _item(
        fields=(_field(), _page_number()),
        second_fields=(_field(value=13.5), _page_number()),
        adjudication=ExtractionAdjudication(
            adjudicator_id="a3", adjudicated_on=TODAY,
            fields=(_field(value=13.5),),
            disagreement_reason="the print is smudged; 13.5 on magnification",
        ),
    )
    result = score(_corpus(item), {"d-1": [_system(value=13.4)]})
    assert result.found == 1
    assert result.wrong_value_persisted == 1


# --- the extraction gate --------------------------------------------
def _big(documents, *, fabricate=0):
    items, outputs = [], {}
    for i in range(documents):
        document_id = f"d-{i}"
        fields = (
            _field(),
            _field(analyte="wbc", label="WBC", value=7.2, unit="10^9/L",
                   ref="4.0 - 11.0"),
            _field(analyte="platelets", label="Platelet Count", value=240.0,
                   unit="10^9/L", ref="150 - 450"),
            _page_number(),
        )
        items.append(_item(document_id=document_id, fields=fields))
        outputs[document_id] = [
            _system(value=1.0 if i < fabricate else 13.4),
            _system(analyte="wbc", label="WBC", value=7.2, unit="10^9/L",
                    ref="4.0 - 11.0"),
            _system(analyte="platelets", label="Platelet Count", value=240.0,
                    unit="10^9/L", ref="150 - 450"),
        ]
    return ExtractionCorpus(corpus_id="big", items=items), outputs


def test_a_perfect_parser_on_a_tiny_corpus_is_not_ready():
    corpus, outputs = _big(10)
    decision = evaluate_extraction(score(corpus, outputs))
    assert not decision.promotable
    unmet = {r.key for r in decision.unmet}
    assert {"corpus_size", "fields_measured", "refusable_lines"} <= unmet


def test_a_parser_measured_at_scale_with_no_fabrications_is_ready():
    corpus, outputs = _big(MIN_EXTRACTION_DOCUMENTS)
    result = score(corpus, outputs)
    assert result.expected >= MIN_EXTRACTED_FIELDS
    assert result.refusable_lines >= MIN_REFUSABLE_LINES

    decision = evaluate_extraction(result)
    assert decision.promotable, [r.detail for r in decision.unmet]


def test_one_fabrication_blocks_the_gate_however_large_the_corpus():
    """The one correctness bar in either benchmark. A value the report does not
    print cannot be acted on, and no corpus size makes that acceptable."""
    corpus, outputs = _big(MIN_EXTRACTION_DOCUMENTS, fabricate=1)
    decision = evaluate_extraction(score(corpus, outputs))

    assert not decision.promotable
    assert "no_fabrications" in {r.key for r in decision.unmet}
    assert any("cannot be acted on" in r.detail for r in decision.unmet)


def test_no_corpus_at_all_is_reported_as_never_measured():
    decision = evaluate_extraction(None)
    assert not decision.promotable
    assert decision.summary == "never measured"


# --- the adapter from the real pipeline ------------------------------
def test_a_real_document_result_converts_into_system_values(text_pdf):
    """The adapter lives beside the loader so a drift between what the
    annotator records and what the pipeline produces is obvious."""
    from intelligence.benchmark.extraction import system_values
    from intelligence.document.pipeline import process_document

    result = process_document(
        text_pdf([
            "COMPLETE BLOOD COUNT",
            "Hemoglobin 13.4 g/dL 13.0 - 17.0",
            "WBC 7.2 10^9/L 4.0 - 11.0",
            "Platelet Count 240 10^9/L 150 - 450",
        ]),
        declared_type="application/pdf",
    )
    values = system_values(result)
    haemoglobin = next(v for v in values if v.analyte == "hemoglobin")

    assert haemoglobin.value == 13.4
    assert haemoglobin.unit == "g/dL"
    assert haemoglobin.reference_text == "13.0 - 17.0"
    assert haemoglobin.section == "COMPLETE BLOOD COUNT"
    assert haemoglobin.persists_clinical_value is True
    assert haemoglobin.status == "OBSERVED"


def test_the_adapter_carries_a_refusal_through_as_a_refusal(text_pdf):
    from intelligence.benchmark.extraction import system_values
    from intelligence.document.pipeline import process_document

    result = process_document(
        text_pdf([
            "COMPLETE BLOOD COUNT",
            "Hemoglobin 1 3.4 g/dL 13.0 - 17.0",
            "WBC 7.2 10^9/L 4.0 - 11.0",
            "Platelet Count 240 10^9/L 150 - 450",
        ]),
        declared_type="application/pdf",
    )
    haemoglobin = next(
        v for v in system_values(result) if v.analyte == "hemoglobin"
    )
    assert haemoglobin.persists_clinical_value is False
    assert haemoglobin.reason == "more_than_one_number_on_the_line"
