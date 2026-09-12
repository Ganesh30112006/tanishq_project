"""The document-intelligence service, used as a second reader.

The existing pipeline works. Reports flow through it today, clinicians act on
what it produces, and replacing its extraction wholesale would put every one of
those reports at risk in exchange for a capability nobody has measured yet -
the benchmark corpora do not exist, so "the new parser is better" is a belief,
not a finding.

So the service is wired in as a **second reader whose opinion may only make the
outcome more conservative**. That is the acceptance condition, and it is an
invariant rather than an intention:

    a report the existing pipeline would FINALIZE may be held for review
    a report the existing pipeline would hold may NEVER be finalized

Nothing the service returns is persisted as a clinical value. It does not
create a ``ReportTest``, does not touch ``Provenance``, and does not change a
number. It can do exactly one thing: say "a person should look at this", with a
reason, in cases the existing path would have passed.

Three modes, set by ``settings.DOCUMENT_INTELLIGENCE["MODE"]``:

``off``       the default. Not called at all; behaviour is unchanged.
``shadow``    called, and what it said is recorded in the audit trail. The
              outcome is untouched. This is the mode to run first, because it
              produces the comparison that would justify going further.
``advisory``  called, and may hold a report that would otherwise finalize.

**Availability is never a clinical dependency.** Every failure - the service
down, a timeout, a malformed response, a missing credential - produces "no
opinion" and the pipeline continues exactly as it would have. A report must not
become unprocessable because an optional service is unreachable.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from django.conf import settings

from apps.common.enums import ReportClass

#: Modes, worst-understood last.
OFF = "off"
SHADOW = "shadow"
ADVISORY = "advisory"
MODES = (OFF, SHADOW, ADVISORY)

#: Dispositions from the service that mean a person should look. Anything not
#: listed is treated as "no concern raised", so a disposition this code has
#: never heard of cannot silently hold a report.
_HOLDING_DISPOSITIONS = frozenset({"NEEDS_REVIEW", "UNREADABLE", "REJECTED_FILE"})

#: Value statuses the service can return that mean it could not stand behind a
#: number. Only ``CONFLICTING`` and ``INVALID`` hold a report on their own: the
#: others mean the service could not read something, which is not evidence that
#: the existing pipeline read it wrongly.
_HOLDING_VALUE_STATUSES = frozenset({"CONFLICTING", "INVALID"})


@dataclass(slots=True)
class SecondOpinion:
    """What the service said, and whether it justifies holding the report."""

    #: False when the service was not called, or could not be reached.
    consulted: bool = False
    available: bool = False
    disposition: str = ""
    report_type: str = ""
    #: Reasons a person should look, in the order they were found.
    concerns: list[str] = field(default_factory=list)
    #: Why no opinion was formed, when that is the case.
    unavailable_reason: str = ""
    #: Everything worth putting in the audit record.
    detail: dict = field(default_factory=dict)

    @property
    def holds_report(self) -> bool:
        return self.available and bool(self.concerns)

    def as_audit_metadata(self) -> dict:
        return {
            "consulted": self.consulted,
            "available": self.available,
            "disposition": self.disposition,
            "report_type": self.report_type,
            "concerns": self.concerns[:10],
            "unavailable_reason": self.unavailable_reason,
            **self.detail,
        }


def mode() -> str:
    configured = getattr(settings, "DOCUMENT_INTELLIGENCE", {}).get("MODE", OFF)
    return configured if configured in MODES else OFF


def consult(report, content: bytes, *, client=None) -> SecondOpinion:
    """Ask the service about this document. Never raises, never persists.

    ``content`` is the bytes Django has already resolved and authorized. The
    service receives those and nothing else - no storage path, no patient id,
    nothing it could use to fetch something on its own.
    """
    current = mode()
    if current == OFF:
        return SecondOpinion(consulted=False, unavailable_reason="mode is off")
    if not content:
        return SecondOpinion(
            consulted=False, unavailable_reason="no document content to send"
        )

    try:
        client = client or _default_client()
        result = client.process_document(
            document_id=str(report.public_id),
            content=content,
            declared_media_type=_media_type(report),
            document_type_hint=_hint(report),
            correlation_id=f"second-reader-{uuid.uuid4().hex[:12]}",
        )
    except Exception as exc:  # noqa: BLE001 - availability is never clinical
        # Deliberately broad. A second reader that can make a report
        # unprocessable is not a second reader, it is a new dependency.
        return SecondOpinion(
            consulted=True,
            available=False,
            unavailable_reason=f"{type(exc).__name__}: {exc}"[:200],
        )

    return _read(result)


def _read(result) -> SecondOpinion:
    opinion = SecondOpinion(
        consulted=True,
        available=True,
        disposition=result.disposition,
        report_type=result.report_type or "",
    )

    if result.disposition in _HOLDING_DISPOSITIONS:
        opinion.concerns.append(
            f"the document service could not complete a clean extraction "
            f"({result.disposition})"
        )

    for issue in result.issues:
        if issue.get("severity") == "HIGH":
            opinion.concerns.append(
                f"{issue.get('code', 'ISSUE')}: {issue.get('detail', '')}".strip(": ")
            )

    flagged: dict[str, list[str]] = {}
    for value in result.values:
        status = value.get("status", "")
        if status in _HOLDING_VALUE_STATUSES:
            flagged.setdefault(status, []).append(
                value.get("analyte") or value.get("printed_label") or "?"
            )
    for status, analytes in sorted(flagged.items()):
        opinion.concerns.append(
            f"{status.lower()} on second reading: {', '.join(sorted(set(analytes)))}"
        )

    opinion.detail = {
        "values_read": len(result.values),
        "values_persistable": sum(
            1 for v in result.values if v.get("persists_clinical_value")
        ),
        "completeness": (result.completeness or {}).get("outcome", ""),
        "text_source": result.text_source,
    }
    return opinion


def _media_type(report) -> str:
    declared = (getattr(report, "mime_type", "") or "").strip()
    return declared or "application/octet-stream"


def _hint(report) -> str:
    """Translate Django's report class into the service's vocabulary.

    The two enums are kept aligned deliberately, so this is a pass-through for
    everything they share and an empty hint for anything they do not - never a
    guess.
    """
    value = (report.class_hint or report.report_class or "").strip()
    return value if value in set(ReportClass.values) else ""


def _default_client():
    from apps.common.intelligence import IntelligenceClient

    return IntelligenceClient()
