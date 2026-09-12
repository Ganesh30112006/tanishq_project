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
from apps.reports import reader_comparison, second_reader
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

    def _classification(self, comparisons) -> None:
        """How often the second reader would not name the document, and what
        that cost.

        Extraction is schema-driven, so a document it will not classify yields
        nothing at all. That is the safe choice; this is its price. Reported
        separately from classifier accuracy, because "how often is it wrong"
        and "how much evidence does abstaining forgo" are different questions
        with different answers and different fixes.
        """
        answered = comparisons.filter(second_available=True)
        total = answered.count()
        if not total:
            return

        abstained = answered.exclude(classification_reason="")
        classified = total - abstained.count()

        self.stdout.write("")
        self.stdout.write("Classification")
        self.stdout.write("=" * 72)
        self.stdout.write(f"reports read              {total}")
        self.stdout.write(f"classified                {classified}")
        self.stdout.write(f"abstained                 {abstained.count()}")
        for reason, count in sorted(
            abstained.values_list("classification_reason").annotate(n=Count("id"))
        ):
            self.stdout.write(f"  {reason:<24s} {count}")

        extracted = sum(answered.values_list("second_value_count", flat=True))
        forgone = sum(abstained.values_list("values_forgone", flat=True))
        self.stdout.write("")
        self.stdout.write(f"values extracted          {extracted}")
        self.stdout.write(f"values forgone            {forgone}")
        self.stdout.write(
            "    Results visible on documents the reader would not name, and "
            "so did not"
        )
        self.stdout.write(
            "    extract. An upper bound: without a schema there are no "
            "plausibility"
        )
        self.stdout.write(
            "    bounds and no completeness check, so some would not have "
            "survived."
        )
        if forgone:
            share = forgone / (forgone + extracted) if (forgone + extracted) else 0
            self.stdout.write(
                f"    {share:.1%} of the results seen were forgone this way."
            )

    def _profile(self, comparisons) -> None:
        """One line per report, and the rate that matters at this stage.

        The headline is **unsafe disagreements per 100 reports**: both readers
        produced a number they stand behind, and the numbers differ. One of
        them is a wrong clinical value carried with full confidence, and
        nothing in either output says which.

        The denominator is reports where the second reader actually answered.
        A report it could not be consulted about never had the opportunity to
        disagree, and counting those would let an outage look like safety.
        """
        buckets = {
            "unsafe disagreement": 0,
            "unresolved disagreement": 0,
            "OCR failure": 0,
            "safe abstention": 0,
            "agreement": 0,
        }
        comparable = 0
        for comparison in comparisons.filter(second_available=True).prefetch_related(
            "disagreements"
        ):
            comparable += 1
            rows = list(comparison.disagreements.all())
            # Worst first: a report with one unsafe row is an unsafe report,
            # whatever else it also contains.
            if any(row.is_unsafe for row in rows):
                buckets["unsafe disagreement"] += 1
            elif any(row.classification == Classification.UNKNOWN for row in rows):
                buckets["unresolved disagreement"] += 1
            elif any(
                row.classification == Classification.OCR_FAILURE for row in rows
            ):
                buckets["OCR failure"] += 1
            elif rows:
                buckets["safe abstention"] += 1
            else:
                buckets["agreement"] += 1

        if not comparable:
            return

        self.stdout.write("")
        self.stdout.write(f"Per report, of {comparable} the second reader answered")
        self.stdout.write("=" * 72)
        for name, count in buckets.items():
            share = count / comparable
            self.stdout.write(f"{name:<26s} {count:>6d}   {share:>6.1%}")

        rate = buckets["unsafe disagreement"] / comparable * 100
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"unsafe disagreements per 100 reports: {rate:.1f}"
            )
        )
        self.stdout.write(
            "    This is the number to watch, not agreement. The goal is not "
            "for the two"
        )
        self.stdout.write(
            "    readers to agree; it is that when they disagree, the clinical "
            "record is"
        )
        self.stdout.write("    never made less safe.")
        if comparable < 100:
            self.stdout.write(
                f"    ({buckets['unsafe disagreement']} in {comparable} "
                f"reports. Below 100 the rate moves by whole reports and is "
                f"not yet stable -"
            )
            self.stdout.write("    read the count, and read the examples.)")

    def _summary(self) -> None:
        comparisons = ReaderComparison.objects.all()
        total = comparisons.count()
        if not total:
            current = second_reader.mode()
            self.stdout.write("No reports have been read twice yet.")
            self.stdout.write("")
            if current == second_reader.OFF:
                self.stdout.write(
                    "DOCUMENT_INTELLIGENCE_MODE is off, so the service is not "
                    "consulted. Set it to shadow and process reports."
                )
            else:
                self.stdout.write(
                    f"DOCUMENT_INTELLIGENCE_MODE is {current}, so a comparison "
                    f"is written for every report the service is consulted "
                    f"about. Either no report has been processed since it was "
                    f"switched on, or the service could not be reached - check "
                    f"that it is running and that INTELLIGENCE_SERVICE_TOKEN "
                    f"matches on both processes."
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

        unsafe = differences.filter(
            kind__in=[Kind.VALUE_DIFFERS, Kind.UNIT_DIFFERS],
            second_persistable=True,
        ).count()

        self._classification(comparisons)
        self._profile(comparisons)

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
