"""The shadow dataset: what it records, and what it refuses to conclude.

Shadow mode's product is not "the service answered". It is a set of real
disagreements on real reports, each kept with the text that caused it, so that
a person can say which reader was right. These tests hold that record to two
properties:

* it preserves the disagreements, including the ones that change nothing;
* it never invents a classification. Which reader was wrong is a judgement
  made by looking at the document, and only three classes follow from the
  responses themselves.

And one property of the integration: writing this record is research, so a
failure to write it cannot touch the report.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from apps.common.enums import (
    ClinicalDataState,
    ReportClass,
    ReportProcessingState,
)
from apps.reports import reader_comparison, second_reader
from apps.reports.models import (
    ReaderComparison,
    ReaderDisagreement,
    Report,
    ReportTest,
)
from apps.reports.pipeline import ReportPipeline
from apps.reports.second_reader import SecondOpinion

pytestmark = pytest.mark.django_db

Kind = ReaderDisagreement.Kind
Classification = ReaderDisagreement.Classification

CLEAN_GLUCOSE = """
CHEMISTRY
Collected: 2024-05-01 09:00
Reported: 2024-05-01 15:00
Glucose: 5.4 mmol/L
"""


# --- helpers ---------------------------------------------------------
class _FakeResult:
    def __init__(self, *, disposition="EXTRACTED", values=None, issues=None):
        self.disposition = disposition
        self.values = values or []
        self.issues = issues or []
        self.report_type = "GLUCOSE"
        self.completeness = {"outcome": "COMPLETE"}
        self.text_source = "EMBEDDED_TEXT_LAYER"


class _FakeClient:
    def __init__(self, result):
        self.result = result

    def process_document(self, **kwargs):
        return self.result


def _their_value(
    analyte, value, unit, *, status="OBSERVED", persists=True, reason="",
    label="", source_text="", normalized=None,
):
    return {
        "analyte": analyte,
        "printed_label": label or analyte,
        "value": value,
        "unit": unit,
        "status": status,
        "reason": reason,
        "persists_clinical_value": persists,
        "normalized": normalized,
        "provenance": {"source_text": source_text or f"{analyte} {value} {unit}"},
    }


def _our_test(name, raw, unit, *, normalized=None, state=ClinicalDataState.OBSERVED):
    return ReportTest(
        name=name, value_raw=str(raw), unit_raw=unit, state=state,
        value_normalized=None if normalized is None else Decimal(str(normalized)),
    )


def _opinion(values, *, disposition="EXTRACTED", concerns=()):
    opinion = SecondOpinion(
        consulted=True, available=True, disposition=disposition,
        report_type="GLUCOSE", concerns=list(concerns),
    )
    opinion.values = values
    return opinion


def _compare(tests, opinion, outcome=ReportProcessingState.FINALIZED):
    return reader_comparison.compare(
        existing_outcome=outcome, tests=tests, opinion=opinion
    )


def _upload(patient, uploader, text=CLEAN_GLUCOSE):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.reports.services import ReportService

    handle = SimpleUploadedFile(
        "r.pdf", b"%PDF-1.4 test", content_type="application/pdf"
    )
    return ReportService().register_upload(
        patient=patient, uploaded_file=handle, uploaded_by=uploader,
        class_hint=ReportClass.GLUCOSE, extracted_text=text,
    )


# --- what counts as agreement ----------------------------------------
class TestAgreement:
    def test_two_readers_reading_the_same_thing_leave_no_record(self):
        comparison = _compare(
            [_our_test("glucose", "5.4", "mmol/L")],
            _opinion([_their_value("glucose", 5.4, "mmol/L")]),
        )
        assert comparison.differences == []
        assert comparison.agreed

    def test_a_silent_service_is_not_agreement(self):
        """No opinion is recorded as no opinion, never as a second reader who
        happened to concur."""
        opinion = SecondOpinion(
            consulted=True, available=False, unavailable_reason="timeout"
        )
        comparison = _compare([_our_test("glucose", "5.4", "mmol/L")], opinion)
        assert comparison.differences == []
        assert not comparison.agreed
        assert comparison.unavailable_reason == "timeout"


# --- what counts as a disagreement -----------------------------------
class TestTheDisagreementsAreKept:
    def test_a_different_number_for_the_same_analyte(self):
        comparison = _compare(
            [_our_test("glucose", "5.4", "mmol/L")],
            _opinion([_their_value("glucose", 15.4, "mmol/L")]),
        )
        difference, = comparison.differences
        assert difference.kind == Kind.VALUE_DIFFERS
        assert difference.existing_value == "5.4"
        assert difference.second_value == "15.4"

    def test_the_same_measurement_in_different_units_is_a_unit_difference(self):
        """13.4 g/dL and 134 g/L are one measurement and two printings. That is
        a different problem from two readers reading different digits, and it
        is fixed by a different change."""
        comparison = _compare(
            [_our_test("hemoglobin", "13.4", "g/dL", normalized="134")],
            _opinion([
                _their_value(
                    "hemoglobin", 134, "g/L",
                    normalized={"value": 134.0, "unit": "g/L"},
                )
            ]),
        )
        difference, = comparison.differences
        assert difference.kind == Kind.UNIT_DIFFERS

    def test_a_result_only_the_existing_reader_found(self):
        comparison = _compare(
            [_our_test("glucose", "5.4", "mmol/L")], _opinion([])
        )
        difference, = comparison.differences
        assert difference.kind == Kind.ONLY_EXISTING
        assert difference.analyte == "glucose"

    def test_a_result_only_the_second_reader_found_keeps_the_line(self):
        """Newly detected evidence and fabrication look identical here, so the
        printed line is kept: it is what the adjudication needs."""
        comparison = _compare(
            [],
            _opinion([
                _their_value(
                    "hba1c", 6.2, "%", label="HbA1c",
                    source_text="HbA1c ........ 6.2 %",
                )
            ]),
        )
        difference, = comparison.differences
        assert difference.kind == Kind.ONLY_SECOND
        assert difference.printed_label == "HbA1c"
        assert difference.excerpt == "HbA1c ........ 6.2 %"

    def test_a_value_the_second_reader_would_not_stand_behind(self):
        comparison = _compare(
            [_our_test("tsh", "0.01", "uIU/mL")],
            _opinion([
                _their_value(
                    "tsh", None, "uIU/mL", status="AMBIGUOUS", persists=False,
                    reason="result_is_a_bound_not_a_number",
                    source_text="TSH <0.01 uIU/mL",
                )
            ]),
        )
        difference, = comparison.differences
        assert difference.kind == Kind.NOT_PERSISTABLE
        assert difference.second_reason == "result_is_a_bound_not_a_number"

    def test_readers_that_would_route_the_report_differently(self):
        comparison = _compare(
            [_our_test("glucose", "5.4", "mmol/L")],
            _opinion(
                [_their_value("glucose", 5.4, "mmol/L")],
                disposition="NEEDS_REVIEW",
                concerns=["the page was cut off"],
            ),
            outcome=ReportProcessingState.FINALIZED,
        )
        kinds = {d.kind for d in comparison.differences}
        assert Kind.ROUTING_DIFFERS in kinds

    def test_an_unreadable_document_is_recorded_as_one(self):
        comparison = _compare(
            [_our_test("glucose", "5.4", "mmol/L")],
            _opinion([], disposition="UNREADABLE"),
        )
        kinds = {d.kind for d in comparison.differences}
        assert Kind.DOCUMENT_UNREADABLE in kinds


# --- what the machine may conclude -----------------------------------
class TestTheMachineDoesNotDecideWhoWasWrong:
    def test_a_different_number_is_left_unclassified(self):
        """The dangerous case, and the one the machine has least business
        labelling: both readers stand behind a number, and neither of them
        knows what the report says."""
        comparison = _compare(
            [_our_test("glucose", "5.4", "mmol/L")],
            _opinion([_their_value("glucose", 15.4, "mmol/L")]),
        )
        difference, = comparison.differences
        assert difference.classification == Classification.UNKNOWN
        assert difference.classified_by == ""

    def test_a_newly_detected_value_is_left_unclassified(self):
        comparison = _compare([], _opinion([_their_value("hba1c", 6.2, "%")]))
        difference, = comparison.differences
        assert difference.classification == Classification.UNKNOWN

    def test_an_abstention_is_classified_from_the_response_itself(self):
        comparison = _compare(
            [_our_test("tsh", "0.01", "uIU/mL")],
            _opinion([
                _their_value(
                    "tsh", None, "uIU/mL", status="AMBIGUOUS", persists=False,
                    reason="result_is_a_bound_not_a_number",
                )
            ]),
        )
        difference, = comparison.differences
        assert difference.classification == Classification.SAFE_ABSTENTION
        assert difference.classified_by == "observed"

    def test_a_conflict_is_classified_from_the_response_itself(self):
        comparison = _compare(
            [_our_test("glucose", "5.4", "mmol/L")],
            _opinion([
                _their_value(
                    "glucose", 5.4, "mmol/L", status="CONFLICTING",
                    persists=False, reason="two_results_for_one_analyte",
                )
            ]),
        )
        difference, = comparison.differences
        assert difference.classification == Classification.CONFLICT_DETECTION

    def test_only_three_classes_are_ever_assigned_without_a_person(self):
        observable = {
            Classification.SAFE_ABSTENTION,
            Classification.CONFLICT_DETECTION,
            Classification.OCR_FAILURE,
            Classification.UNKNOWN,
        }
        cases = [
            _compare([_our_test("glucose", "5.4", "mmol/L")], _opinion([])),
            _compare([], _opinion([_their_value("hba1c", 6.2, "%")])),
            _compare(
                [_our_test("glucose", "5.4", "mmol/L")],
                _opinion([_their_value("glucose", 9.9, "mmol/L")]),
            ),
            _compare(
                [_our_test("glucose", "5.4", "mmol/L")],
                _opinion([], disposition="UNREADABLE"),
            ),
        ]
        for comparison in cases:
            for difference in comparison.differences:
                assert difference.classification in observable, (
                    f"{difference.kind} was classified "
                    f"{difference.classification} by the machine. Attributing "
                    f"an error to a reader needs the document."
                )


# --- a person's ruling ------------------------------------------------
class TestClassifyingByHand:
    @pytest.fixture
    def disagreement(self, make_patient, make_user):
        report = _upload(make_patient(), make_user())
        comparison = _compare(
            [_our_test("glucose", "5.4", "mmol/L")],
            _opinion([_their_value("glucose", 15.4, "mmol/L")]),
        )
        row = reader_comparison.record(
            Report.objects.get(pk=report.pk), comparison,
            mode=second_reader.SHADOW,
        )
        return row.disagreements.get()

    def test_a_ruling_records_who_and_why(self, disagreement):
        reader_comparison.classify(
            disagreement, as_class=Classification.PARSER_ERROR,
            by="dr-mehta", note="the second reader took the next row's number",
        )
        disagreement.refresh_from_db()
        assert disagreement.classification == Classification.PARSER_ERROR
        assert disagreement.classified_by == "dr-mehta"
        assert disagreement.classified_at is not None
        assert "next row" in disagreement.classification_note

    def test_a_ruling_records_the_definitions_in_force(self, disagreement):
        """A ruling is an answer to a question. If the question is later
        reworded, the old answers must not be re-read as answers to the new
        one."""
        assert disagreement.taxonomy_version == ""
        reader_comparison.classify(
            disagreement, as_class=Classification.SAFE_IMPROVEMENT,
            by="dr-mehta", note="the printed value was 15.4",
        )
        disagreement.refresh_from_db()
        assert disagreement.taxonomy_version == reader_comparison.TAXONOMY_VERSION

    def test_a_ruling_without_a_reviewer_is_refused(self, disagreement):
        with pytest.raises(ValueError, match="named reviewer"):
            reader_comparison.classify(
                disagreement, as_class=Classification.PARSER_ERROR,
                by="", note="because",
            )

    def test_a_ruling_without_a_reason_is_refused(self, disagreement):
        """The counts are already known. The written reason is the only part
        that says what to change."""
        with pytest.raises(ValueError, match="needs a reason"):
            reader_comparison.classify(
                disagreement, as_class=Classification.PARSER_ERROR,
                by="dr-mehta", note="",
            )

    def test_unknown_is_not_something_a_reviewer_concludes(self, disagreement):
        with pytest.raises(ValueError, match="starts as"):
            reader_comparison.classify(
                disagreement, as_class=Classification.UNKNOWN,
                by="dr-mehta", note="cannot tell",
            )

    def test_an_invented_class_is_refused(self, disagreement):
        with pytest.raises(ValueError, match="is not one of"):
            reader_comparison.classify(
                disagreement, as_class="PROBABLY_FINE",
                by="dr-mehta", note="looks ok",
            )


# --- the record is written, and cannot hurt the report ----------------
class TestTheRecordIsResearchOnly:
    def test_nothing_is_recorded_with_the_mode_off(
        self, settings, make_patient, make_user
    ):
        settings.DOCUMENT_INTELLIGENCE = {"MODE": "off"}
        report = _upload(make_patient(), make_user())
        ReportPipeline().run(Report.objects.get(pk=report.pk))
        assert not ReaderComparison.objects.exists()

    def test_shadow_mode_records_without_changing_the_outcome(
        self, settings, monkeypatch, make_patient, make_user
    ):
        settings.DOCUMENT_INTELLIGENCE = {"MODE": "shadow"}
        monkeypatch.setattr(
            second_reader, "_default_client",
            lambda: _FakeClient(_FakeResult(
                disposition="NEEDS_REVIEW",
                values=[_their_value("glucose", 15.4, "mmol/L")],
            )),
        )
        report = _upload(make_patient(), make_user())
        result = ReportPipeline().run(Report.objects.get(pk=report.pk))

        assert result.value.state == ReportProcessingState.FINALIZED
        comparison = ReaderComparison.objects.get()
        assert comparison.mode == second_reader.SHADOW
        assert comparison.existing_outcome == ReportProcessingState.FINALIZED
        assert not comparison.agreed
        assert comparison.disagreements.exists()

    def test_an_advisory_hold_still_records_what_the_existing_reader_decided(
        self, settings, monkeypatch, make_patient, make_user
    ):
        """Otherwise the record would say the readers agreed to hold, which is
        the opposite of what happened."""
        settings.DOCUMENT_INTELLIGENCE = {"MODE": "advisory"}
        monkeypatch.setattr(
            second_reader, "_default_client",
            lambda: _FakeClient(_FakeResult(
                disposition="NEEDS_REVIEW",
                values=[_their_value("glucose", 5.4, "mmol/L")],
            )),
        )
        report = _upload(make_patient(), make_user())
        result = ReportPipeline().run(Report.objects.get(pk=report.pk))

        assert result.value.state == ReportProcessingState.REVIEW_REQUIRED
        comparison = ReaderComparison.objects.get()
        assert comparison.existing_outcome == ReportProcessingState.FINALIZED
        assert comparison.mode == second_reader.ADVISORY

    def test_the_record_says_what_kind_of_document_it_was(
        self, settings, monkeypatch, make_patient, make_user
    ):
        """A pilot made entirely of clean PDFs looks complete and is not, so
        the stratum has to be visible in the record itself."""
        settings.DOCUMENT_INTELLIGENCE = {"MODE": "shadow"}
        monkeypatch.setattr(
            second_reader, "_default_client",
            lambda: _FakeClient(_FakeResult(
                values=[_their_value("glucose", 15.4, "mmol/L")]
            )),
        )
        report = _upload(make_patient(), make_user())
        ReportPipeline().run(Report.objects.get(pk=report.pk))

        comparison = ReaderComparison.objects.get()
        assert comparison.report_class == ReportClass.GLUCOSE
        assert comparison.text_source == "EMBEDDED_TEXT_LAYER"

    def test_a_report_is_not_harmed_when_the_record_cannot_be_written(
        self, settings, monkeypatch, make_patient, make_user
    ):
        settings.DOCUMENT_INTELLIGENCE = {"MODE": "shadow"}
        monkeypatch.setattr(
            second_reader, "_default_client",
            lambda: _FakeClient(_FakeResult(
                values=[_their_value("glucose", 5.4, "mmol/L")]
            )),
        )

        def _explode(*args, **kwargs):
            raise RuntimeError("the research table is on fire")

        monkeypatch.setattr(reader_comparison, "compare", _explode)
        report = _upload(make_patient(), make_user())
        result = ReportPipeline().run(Report.objects.get(pk=report.pk))

        assert result.value.state == ReportProcessingState.FINALIZED
        assert not ReaderComparison.objects.exists()

    def test_no_clinical_code_reads_the_shadow_tables(self):
        """A research record that reached a clinical decision would be a second
        reader acting through the back door."""
        import ast
        import pathlib

        allowed = {
            "apps/reports/models.py",
            "apps/reports/reader_comparison.py",
            "apps/reports/management/commands/shadow_disagreements.py",
        }
        root = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for path in (root / "apps").rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            if relative in allowed or "/migrations/" in relative:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in (
                    "ReaderComparison", "ReaderDisagreement"
                ):
                    offenders.append(f"{relative}:{node.lineno}")
        assert not offenders, (
            f"the shadow record is read outside the modules that own it: "
            f"{offenders}"
        )
