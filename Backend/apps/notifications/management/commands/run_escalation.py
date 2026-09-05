from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.notifications.services import EscalationService


class Command(BaseCommand):
    help = "Advance overdue missing-data tasks through their escalation policy (normally scheduled)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options) -> None:
        result = EscalationService().evaluate_overdue(limit=options["limit"])
        self.stdout.write(f"escalated={result['escalated']}")
