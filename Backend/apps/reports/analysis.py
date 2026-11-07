"""The AI's analysis of one report, for the patient who owns it.

There is no doctor in this product, so this module answers the question a
doctor would otherwise have been asked first: of everything the AI read on this
report, what may the patient be shown?

The document service reads the report and builds findings - laboratory
findings, named patterns, and hedged *possible* conditions - each carrying the
evidence it stood on and the report line that evidence came from. This module
decides what of that reaches the patient, and the rule is one-directional:

    the AI may hold back something it read; it may never show something it
    did not stand behind.

Three things are held back, always with a reason the patient can read:

* a value the service itself would not stand behind (it says why);
* a value the existing pipeline read *differently* - two readers disagreeing is
  the clearest sign one of them is wrong, and nothing here can tell which;
* every finding that stood on a held-back value, or on a held-back finding.

Nothing here is a diagnosis and nothing here is a clinical record. Findings are
named as patterns and possibilities, their explanations come only from the
approved knowledge base, and every one tells the patient to show it to a
doctor. The analysis is stored as AI output in :class:`ReportAnalysis`; it
never becomes a ``ReportTest`` and no clinical code path reads it.

**Availability is never a dependency.** A service that is down, slow or broken
produces ``UNAVAILABLE`` - "the AI could not look at this yet" - and nothing
else about the report changes.
"""
from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.utils import timezone

from apps.common.enums import ReportClass
from apps.reports import reader_comparison
from apps.reports.models import Report, ReportAnalysis
from apps.reports.second_reader import SecondOpinion

logger = logging.getLogger("caresense.reports.analysis")

#: Stamped on every analysis. Bump it when what is held back, or why, changes,
#: so an old analysis is never re-read as if the new rules had produced it.
POLICY_VERSION = "patient-analysis-2"  # 2: danger limits as well as printed flags

#: Dispositions meaning the service recovered nothing it could read from.
_UNREADABLE = frozenset({"UNREADABLE", "REJECTED_FILE"})

#: Report types the document service can name that the report model has no
#: class for. Shown to the patient as the kind of report; never used to choose
#: a schema, because there is no one schema for them.
AI_ONLY_TYPES = {"MULTI_PANEL": "Health check"}

#: Kinds of disagreement that withhold a value. Both mean the two readers put
#: different numbers on the same line; which one is wrong is a question for a
#: person with the document, so the AI shows neither.
_DISPUTED_KINDS = frozenset({
    reader_comparison.Kind.VALUE_DIFFERS,
    reader_comparison.Kind.UNIT_DIFFERS,
})

#: Abnormal flags a laboratory prints when a result needs attention now. HH and
#: LL are HL7's "outside panic limits". This is the laboratory's own judgement,
#: read off the report. Many reports print only H or L, so the service also
#: marks a value past a wide danger limit (``beyond_critical_limit``, see
#: intelligence/knowledge/critical_limits.py); either one makes a value
#: critical. Both only ever add urgency.
_CRITICAL_FLAGS = frozenset({"CRITICAL_HIGH", "CRITICAL_LOW", "HH", "LL"})

# Value states shown to the patient.
USED = "USED"
NOT_SURE = "NOT_SURE"
READERS_DISAGREE = "READERS_DISAGREE"

# Patient-facing reasons. Simple Indian English, no jargon.
_REASONS = {
    "disabled": "AI analysis is switched off right now.",
    "no_consent": (
        "You have not allowed our AI to read your reports. You can turn this "
        "on in Settings, then ask again."
    ),
    "no_file": "We could not find the file for this report.",
    "service_unavailable": (
        "Our AI could not look at this report right now. We will try again."
    ),
    "could_not_read": (
        "Our AI could not read this report clearly, so it has not analysed it. "
        "A clearer copy or a PDF from the laboratory may help."
    ),
    "nothing_certain": (
        "Our AI read this report but was not sure enough about any value to "
        "analyse it. Please show the report to a doctor."
    ),
    "readers_disagree": (
        "Our AI read some values differently on a second check, so it has not "
        "used them. Please check those values on your printed report."
    ),
}


def enabled() -> bool:
    return bool(getattr(settings, "AI_ANALYSIS", {}).get("ENABLED", True))


def analyse(report: Report, *, client=None) -> ReportAnalysis:
    """Read the report with the document service and store what may be shown.

    Never raises for a service failure; the outcome is recorded instead.
    """
    if not enabled():
        return _save(report, ReportAnalysis.Status.UNAVAILABLE, "disabled")

    # The same consent the AI chat and the risk estimate require. Stored as
    # UNAVAILABLE - the AI has not looked - so that once the person turns it on
    # in Settings, asking again reads the report.
    from apps.privacy.models import ConsentPurpose
    from apps.privacy.services import privacy_service

    if not privacy_service.permits(report.patient, ConsentPurpose.AI_ASSISTANCE):
        return _save(report, ReportAnalysis.Status.UNAVAILABLE, "no_consent")

    from apps.reports.ocr import read_report_bytes

    content = read_report_bytes(report)
    if not content:
        return _save(report, ReportAnalysis.Status.HELD_BACK, "no_file")

    try:
        client = client or _default_client()
        result = client.process_document(
            document_id=str(report.public_id),
            content=content,
            declared_media_type=report.file_content_type or "application/octet-stream",
            document_type_hint=report.class_hint or report.report_class or "",
            correlation_id=f"analysis-{uuid.uuid4().hex[:12]}",
            patient_sex=_sex(report.patient),
            patient_age_years=_age_years(report),
        )
    except Exception as exc:  # noqa: BLE001 - availability is never clinical
        logger.warning("analysis unavailable for %s: %s", report.public_id, type(exc).__name__)
        return _save(report, ReportAnalysis.Status.UNAVAILABLE, "service_unavailable")

    if result.disposition in _UNREADABLE:
        return _save(
            report, ReportAnalysis.Status.HELD_BACK, "could_not_read",
            source_sha256=result.source_sha256, text_source=result.text_source,
        )
    report_type = classified_type(result)

    disputed = disputed_analytes(report, result.values)
    values = [_value_row(v, disputed) for v in result.values]
    findings_block = result.findings or {}
    findings = withhold(findings_block.get("findings") or [], disputed)

    used = [v for v in values if v["state"] == USED]
    shown = [f for f in findings if not f["withheld"]]
    if not used and not shown:
        status, code = ReportAnalysis.Status.HELD_BACK, "nothing_certain"
    else:
        status = ReportAnalysis.Status.READY
        code = "readers_disagree" if any(v["state"] == READERS_DISAGREE for v in values) else ""

    return _save(
        report, status, code,
        report_type=report_type,
        # Urgency errs the other way: a critical flag either reader saw is
        # shown, even on a value held back, because "see a doctor today" is
        # the safe direction to be wrong in.
        urgent=any(v["critical"] for v in values),
        values=values,
        findings=findings,
        unusable=list(findings_block.get("unusable_evidence") or []),
        source_sha256=result.source_sha256,
        text_source=result.text_source,
        knowledge_version=findings_block.get("knowledge_version", ""),
        range_table_version=findings_block.get("range_table_version", ""),
        detectors_run=int(findings_block.get("detectors_run") or 0),
    )


def classified_type(result) -> str:
    """The report type the service's classifier committed to, or "".

    Only a CLASSIFIED result counts. The classifier abstains when a document
    could be two kinds, and an abstention stays empty rather than becoming its
    top guess. Read defensively: the service is deployed separately, and a
    response that predates these fields simply names no type.
    """
    classification = getattr(result, "classification", None) or {}
    if classification.get("status") == "MULTI_PANEL":
        return "MULTI_PANEL"  # a health check: several panels, read one by one
    if classification.get("status") != "CLASSIFIED":
        return ""
    value = getattr(result, "report_type", None) or classification.get("type") or ""
    if value == ReportClass.OTHER or value not in ReportClass.values:
        return ""
    return value


def disputed_analytes(report: Report, second_values: list[dict]) -> set[str]:
    """Analytes, lower-cased, that the existing pipeline read differently."""
    tests = list(report.tests.all())
    if not tests or not second_values:
        return set()
    opinion = SecondOpinion(consulted=True, available=True, values=list(second_values))
    comparison = reader_comparison.compare(
        existing_outcome=report.processing_state, tests=tests, opinion=opinion,
        report_class=report.report_class,
    )
    return {
        d.analyte.strip().lower()
        for d in comparison.differences
        if d.kind in _DISPUTED_KINDS and d.analyte
    }


def withhold(findings: list[dict], disputed: set[str]) -> list[dict]:
    """Mark every finding that stood on a disputed value, directly or not.

    Findings arrive lowest level first - the order they were built in - so one
    pass carries a withheld pattern up to every condition built on it.
    """
    withheld_codes: set[str] = set()
    out: list[dict] = []
    for finding in sorted(findings, key=lambda f: int(f.get("level") or 0)):
        refs = finding.get("evidence_used") or []
        measured = {
            (r.get("key") or "").lower() for r in refs if r.get("kind") != "finding"
        }
        built_on = {r.get("key") or "" for r in refs if r.get("kind") == "finding"}
        reason = ""
        if measured & disputed:
            reason = "It uses a value our AI read differently on a second check."
        elif built_on & withheld_codes:
            reason = "It builds on another result our AI has held back."
        if reason:
            withheld_codes.add(finding.get("code") or "")
        out.append(_finding_row(finding, withheld=bool(reason), reason=reason))
    return out


def _value_row(value: dict, disputed: set[str]) -> dict:
    analyte = (value.get("analyte") or "").strip()
    prov = value.get("provenance") or {}
    ref = value.get("reference_range") or {}
    if analyte.lower() in disputed:
        state, note = READERS_DISAGREE, _REASONS["readers_disagree"]
    elif not value.get("persists_clinical_value"):
        state, note = NOT_SURE, _not_sure_note(value.get("reason") or "")
    else:
        state, note = USED, ""
    flag = (value.get("printed_flag") or "").upper()
    if flag in _CRITICAL_FLAGS:
        critical_source = "LAB_FLAG"
    elif value.get("beyond_critical_limit"):
        critical_source = "DANGER_LIMIT"
    else:
        critical_source = ""
    return {
        "analyte": analyte,
        "label": value.get("printed_label") or analyte,
        "value": value.get("value"),
        "unit": value.get("unit") or "",
        "reference_text": ref.get("text") or "",
        "reference_status": value.get("reference_status") or "",
        "printed_flag": flag,
        "critical": bool(critical_source),
        "critical_source": critical_source,
        "page": prov.get("page"),
        "source_text": prov.get("source_text") or "",
        "text_source": prov.get("text_source") or "",
        "state": state,
        "note": note,
    }


def _finding_row(finding: dict, *, withheld: bool, reason: str) -> dict:
    return {
        "code": finding.get("code") or "",
        "label": finding.get("label") or "",
        "plain_name": finding.get("plain_name") or "",
        "plain_explanation": finding.get("plain_explanation") or "",
        "next_steps": list(finding.get("next_steps") or []),
        "level": int(finding.get("level") or 0),
        "category": finding.get("category") or "",
        "confidence": finding.get("confidence") or "",
        "validation_status": finding.get("validation_status") or "",
        "evidence_used": [
            {
                "key": r.get("key") or "",
                "kind": r.get("kind") or "",
                "value": r.get("value"),
                "unit": r.get("unit") or "",
                "reference_text": r.get("reference_text") or "",
                "reference_status": r.get("reference_status") or "",
                "page": r.get("page"),
                "source_text": r.get("source_text") or "",
            }
            for r in finding.get("evidence_used") or []
        ],
        "evidence_missing": list(finding.get("evidence_missing") or []),
        "caveats": list(finding.get("caveats") or []),
        "withheld": withheld,
        "withheld_reason": reason,
    }


#: Why a value was not used, in words a patient can follow. Anything not listed
#: gets the general sentence: a machine code must never reach the screen.
_NOT_SURE_NOTES = {
    "unrecognised_analyte": "Our AI does not know this test yet, so it has not used this value.",
    "no_unit": "Our AI could not find a unit for this value, so it has not used it.",
    "unit_not_convertible_for_analyte": "Our AI does not know this unit for this test, so it has not used this value.",
    "outside_plausibility_bounds": (
        "This number looks too high or too low to be a real result, so our AI has not "
        "used it. Please check it on your printed report."
    ),
    "more_than_one_number_on_the_line": (
        "Our AI found more than one number here and could not tell which is the result, "
        "so it has not used it."
    ),
    "result_is_a_bound_not_a_number": "This result is given as a limit, not an exact number, so our AI has not used it.",
    "value_is_not_numeric": "Our AI could not find a clear number here, so it has not used it.",
    "ocr_readings_disagree": (
        "Our AI read this part of the scan twice and got different answers, so it has "
        "not used this value. Please check it on your printed report."
    ),
    "outside_any_panel": "Our AI could not tell which part of the report this value belongs to, so it has not used it.",
    "same_analyte_reported_with_different_values": (
        "This report shows this test more than once with different numbers, so our AI has not used it."
    ),
    "printed_flag_disagrees_with_range": (
        "The high or low mark on the report does not match the printed range, so our AI "
        "has not used this value."
    ),
    "reference_range_unparseable": "Our AI could not read the normal range for this value, so it has not used it.",
    "reference_unit_not_comparable": "The normal range is printed in a different unit, so our AI has not used this value.",
}


def _not_sure_note(reason: str) -> str:
    if reason == "ocr_number_uncertain":
        return (
            "Our AI could not read this number clearly on the scan, so it has not "
            "used it. Please check it on your printed report."
        )
    return _NOT_SURE_NOTES.get(reason, "Our AI was not sure about this value, so it has not used it.")


def _save(report: Report, status: str, code: str, **fields) -> ReportAnalysis:
    defaults = {
        "status": status,
        "reason_code": code,
        "reason": _REASONS.get(code, ""),
        "urgent": False,
        "values": [],
        "findings": [],
        "unusable": [],
        "report_type": "",
        "source_sha256": "",
        "text_source": "",
        "knowledge_version": "",
        "range_table_version": "",
        "detectors_run": 0,
        **fields,
        "report_version": report.version,
        "policy_version": POLICY_VERSION,
    }
    analysis, _ = ReportAnalysis.objects.update_or_create(report=report, defaults=defaults)
    return analysis


def _sex(patient) -> str:
    value = (getattr(patient, "sex", "") or "").upper()
    return {"MALE": "male", "FEMALE": "female"}.get(value, "")


def _age_years(report: Report) -> float | None:
    born = getattr(report.patient, "date_of_birth", None)
    if born is None:
        return None
    on = (report.collected_at or timezone.now()).date()
    if on < born:
        return None
    return round((on - born).days / 365.25, 1)


def _default_client():
    from apps.common.intelligence import IntelligenceClient

    return IntelligenceClient()


__all__ = ["POLICY_VERSION", "analyse", "disputed_analytes", "enabled", "withhold"]
