from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.data_quality.jobs import sweep


class Command(BaseCommand):
    help = "Run the data-quality + anomaly sweep once (normally scheduled as a job)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options) -> None:
        result = sweep({"limit": options["limit"]})
        self.stdout.write(
            f"assessed={result['assessed']} anomaly_flags={result['anomaly_flags']}"
        )
