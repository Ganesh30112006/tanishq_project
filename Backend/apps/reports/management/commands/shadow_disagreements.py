"""Report what shadow mode has found, and let a person classify it.

    python manage.py shadow_disagreements
    python manage.py shadow_disagreements --unclassified --limit 40
    python manage.py shadow_disagreements --coverage
    python manage.py shadow_disagreements --kind VALUE_DIFFERS
    python manage.py shadow_disagreements --classify <id> --as PARSER_ERROR \\
        --by "dr-mehta" --note "the second reader took the previous row's unit"

The summary is counts of *kinds*, not a score. An agreement percentage is
printed at the bottom and is labelled as what it is: two readers can agree and
both be wrong, so agreement measures how similar they are, not whether either
is right.

Nothing here classifies anything automatically. Which reader was wrong is
decided by looking at the document, and a label nobody made is worse than an
empty column, because it looks like evidence.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.common.enums import ReportClass
from apps.reports import reader_comparison
from apps.reports.models import ReaderComparison, ReaderDisagreement

Kind = ReaderDisagreement.Kind
Classification = ReaderDisagreement.Classification


class Command(BaseCommand):
    help = "Summarise, list and classify second-reader disagreements."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument(
            "--coverage", action="store_true",
            help="show which kinds of document the pilot has and has not seen",
        )
        parser.add_argument("--kind", default="", help="filter by disagreement kind")
        parser.add_argument("--analyte", default="")
        parser.add_argument(
            "--unclassified", action="store_true",
            help="list only what is still waiting for a person",
        )
        parser.add_argument("--classify", default="", help="disagreement public id")
        parser.add_argument("--as", dest="as_class", default="")
        parser.add_argument("--by", default="")
        parser.add_argument("--note", default="")

    def handle(self, *args, **options) -> None:
        if options["classify"]:
            self._classify(options)
            return
        if options["coverage"]:
            self._coverage()
            return
        self._summary()
        self._listing(options)

    # ------------------------------------------------------------------
    def _classify(self, options) -> None:
        try:
            row = ReaderDisagreement.objects.get(public_id=options["classify"])
        except (ReaderDisagreement.DoesNotExist, ValueError, TypeError) as exc:
            raise CommandError(f"no disagreement {options['classify']!r}") from exc
        try:
            reader_comparison.classify(
                row,
                as_class=options["as_class"],
                by=options["by"],
                note=options["note"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"{row.public_id} classified {row.classification} by "
                f"{row.classified_by}"
            )
        )

    def _coverage(self) -> None:
        """What the pilot has actually seen.

        A pilot is chosen for diversity, not volume: its job is to find failure
        modes nobody anticipated, and a set made entirely of clean PDFs from
        one laboratory finds the failure modes of clean PDFs from one
        laboratory. This prints the gaps while they can still be filled.
        """
        comparisons = ReaderComparison.objects.all()
        if not comparisons.exists():
            self.stdout.write("No reports have been read twice yet.")
            return

        self.stdout.write("")
        self.stdout.write("What the pilot has seen")
        self.stdout.write("=" * 72)

        self.stdout.write("")
        self.stdout.write(f"{'report type':<22s} {'reports':>8s} {'disagreeing':>12s}")
        self.stdout.write("-" * 46)
        for report_class in [*ReportClass.values, ""]:
            rows = comparisons.filter(report_class=report_class)
            total = rows.count()
            if not total and report_class == "":
                continue
            differing = rows.filter(agreed=False, second_available=True).count()
            label = report_class or "(unclassified)"
            marker = "" if total else "   <- not seen yet"
            self.stdout.write(f"{label:<22s} {total:>8d} {differing:>12d}{marker}")

        self.stdout.write("")
        self.stdout.write(f"{'how the text came':<22s} {'reports':>8s} {'disagreeing':>12s}")
        self.stdout.write("-" * 46)
        sources = dict(
            comparisons.values_list("text_source").annotate(n=Count("id")).order_by()
        )
        for source, count in sorted(sources.items()):
            differing = comparisons.filter(
                text_source=source, agreed=False, second_available=True
            ).count()
            self.stdout.write(
                f"{source or '(none reported)':<22s} {count:>8d} {differing:>12d}"
            )
        if not any(s for s in sources if "OCR" in s.upper()):
            self.stdout.write("")
            self.stdout.write(
                "No OCR capture has been compared yet. Scans and photographs "
                "are where the two readers differ most, so a pilot without "
                "them has not been tested on the reports that matter."
            )

    def _summary(self) -> None:
        comparisons = ReaderComparison.objects.all()
        total = comparisons.count()
        if not total:
            self.stdout.write(
                "No reports have been read twice yet.\n\n"
                "Shadow mode is off, or no report has been processed since it "
                "was switched on. Set DOCUMENT_INTELLIGENCE_MODE=shadow and "
                "process reports; the comparison is written for every report "
                "the service is consulted about."
            )
            return

        unavailable = comparisons.filter(second_available=False).count()
        agreed = comparisons.filter(agreed=True).count()
        differences = ReaderDisagreement.objects.all()

        self.stdout.write("")
        self.stdout.write("Reports read twice")
        self.stdout.write("=" * 72)
        self.stdout.write(f"reports compared          {total}")
        self.stdout.write(f"second reader silent      {unavailable}")
        for mode, count in (
            comparisons.values_list("mode").annotate(n=Count("id")).order_by()
        ):
            self.stdout.write(f"  in {mode:<20s}  {count}")

        self.stdout.write("")
        self.stdout.write("What the disagreements were")
        self.stdout.write("=" * 72)
        by_kind = dict(
            differences.values_list("kind").annotate(n=Count("id")).order_by()
        )
        for kind in Kind.values:
            self.stdout.write(f"{kind:<24s} {by_kind.get(kind, 0)}")

        unsafe = sum(
            1 for d in differences.filter(
                kind__in=[Kind.VALUE_DIFFERS, Kind.UNIT_DIFFERS],
                second_persistable=True,
            )
        )
        self.stdout.write("")
        self.stdout.write("The counts that matter")
        self.stdout.write("=" * 72)
        self.stdout.write(
            f"unsafe disagreements      {unsafe}\n"
            f"    Both readers produced a number they stand behind and the "
            f"numbers differ.\n"
            f"    One of them is wrong and nothing in the outputs says which."
        )
        self.stdout.write(
            f"safe abstentions          "
            f"{differences.filter(kind=Kind.NOT_PERSISTABLE).count()}\n"
            f"    The second reader read the line and would not stand behind "
            f"it."
        )
        self.stdout.write(
            f"newly detected evidence   "
            f"{differences.filter(kind=Kind.ONLY_SECOND).count()}\n"
            f"    Results only the second reader reported. Candidates for a "
            f"real gain\n    and candidates for fabrication - the document "
            f"decides which."
        )
        self.stdout.write(
            f"missed evidence           "
            f"{differences.filter(kind=Kind.ONLY_EXISTING).count()}\n"
            f"    Results only the existing pipeline reported."
        )
        self.stdout.write(
            f"conflict detection        "
            f"{differences.filter(classification=Classification.CONFLICT_DETECTION).count()}\n"
            f"    The second reader found the same analyte printed twice with "
            f"different results."
        )
        self.stdout.write(
            f"OCR failures              "
            f"{differences.filter(classification=Classification.OCR_FAILURE).count()}"
        )
        self.stdout.write(
            f"routing differs           "
            f"{differences.filter(kind=Kind.ROUTING_DIFFERS).count()}\n"
            f"    One reader would have held the report and the other would "
            f"not."
        )

        self.stdout.write("")
        self.stdout.write("fabrications              cannot be counted from this table")
        self.stdout.write(
            "    A fabrication is a value the report does not support, and "
            "neither reader\n    knows what the report says. The extraction "
            "benchmark measures this;\n    ONLY_SECOND rows are where to look "
            "for candidates."
        )

        self.stdout.write("")
        self.stdout.write("Classification")
        self.stdout.write("=" * 72)
        by_class = dict(
            differences.values_list("classification").annotate(n=Count("id")).order_by()
        )
        for name in Classification.values:
            count = by_class.get(name, 0)
            observed = (
                "  (from the response itself)"
                if name in (
                    Classification.CONFLICT_DETECTION,
                    Classification.OCR_FAILURE,
                    Classification.SAFE_ABSTENTION,
                ) else ""
            )
            self.stdout.write(f"{name:<28s} {count}{observed}")
        pending = by_class.get(Classification.UNKNOWN, 0)
        if pending:
            self.stdout.write(
                f"\n{pending} disagreements are waiting for a person. Which "
                f"reader was wrong cannot be\nread off the two outputs - it "
                f"needs the document."
            )

        rate = agreed / total if total else 0.0
        self.stdout.write("")
        self.stdout.write(
            f"(Agreement {rate:.1%} of {total}. Not a safety measure: two "
            f"readers can agree\nand both be wrong. It is here to show how "
            f"much of the record is disagreement.)"
        )

    def _listing(self, options) -> None:
        rows = ReaderDisagreement.objects.select_related("comparison__report")
        if options["kind"]:
            rows = rows.filter(kind=options["kind"])
        if options["analyte"]:
            rows = rows.filter(analyte__iexact=options["analyte"])
        if options["unclassified"]:
            rows = rows.filter(classification=Classification.UNKNOWN)
        rows = rows.order_by("-created_at")[: max(options["limit"], 0)]
        if not rows:
            return

        self.stdout.write("")
        self.stdout.write("Examples")
        self.stdout.write("=" * 72)
        for row in rows:
            self.stdout.write("")
            self.stdout.write(f"{row.public_id}  {row.kind}  {row.analyte or '-'}")
            self.stdout.write(
                f"    report        {row.comparison.report.public_id} "
                f"({row.comparison.mode}, existing said "
                f"{row.comparison.existing_outcome})"
            )
            self.stdout.write(
                f"    existing      {row.existing_value or '-'} "
                f"{row.existing_unit} [{row.existing_state or '-'}]"
            )
            self.stdout.write(
                f"    second        {row.second_value or '-'} {row.second_unit} "
                f"[{row.second_status or '-'}] {row.second_reason}"
            )
            if row.printed_label:
                self.stdout.write(f"    printed as    {row.printed_label}")
            if row.excerpt:
                self.stdout.write(f"    on the page   {row.excerpt}")
            self.stdout.write(
                f"    classified    {row.classification}"
                + (f" by {row.classified_by}" if row.classified_by else "")
            )
            if row.classification_note:
                self.stdout.write(f"    because       {row.classification_note}")
