"""Report - and optionally apply - data retention.

Reporting is the default. ``--apply`` acts only on the categories marked
``hard_delete``: expired credentials and delivered notifications. Clinical data
is never destroyed by this command; it is listed for a person to decide on.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.privacy.retention import seed_default_policies, sweep


class Command(BaseCommand):
    help = "Report data past its retention period; --apply removes the disposable kind."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Delete expired rows in hard-delete categories (credentials, notifications).",
        )
        parser.add_argument(
            "--seed",
            action="store_true",
            help="Create the default retention policies if they do not exist.",
        )

    def handle(self, *args, **options) -> None:
        if options["seed"]:
            created = seed_default_policies()
            self.stdout.write(f"Seeded {created} retention policy row(s).")

        report = sweep(apply=options["apply"])
        if not report["policies"]:
            self.stdout.write(
                "No retention policies are configured. Run with --seed to create "
                "the defaults, then have a compliance owner review them."
            )
            return

        self.stdout.write(f"Retention report at {report['generated_at']:%Y-%m-%d %H:%M}")
        self.stdout.write(
            f"  {'category':<18} {'keep':>7} {'expired':>8}  action"
        )
        for row in report["policies"]:
            self.stdout.write(
                f"  {row['category']:<18} {row['retain_days']:>6}d "
                f"{row['expired']:>8}  {row['action']}"
            )

        if report["deleted"]:
            self.stdout.write("")
            for category, count in report["deleted"].items():
                self.stdout.write(f"  deleted {count} row(s) from {category}")

        pending = report["needs_human_decision"]
        if pending:
            self.stdout.write("")
            self.stdout.write(
                "The following are past their retention period but are NOT deleted "
                "automatically - destroying clinical data is a decision a person makes:"
            )
            for row in pending:
                self.stdout.write(f"  {row['category']}: {row['expired']} row(s)")
                self.stdout.write(f"    basis: {row['basis']}")
        elif not options["apply"]:
            self.stdout.write("")
            self.stdout.write("Nothing is past its retention period.")
