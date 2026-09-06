"""Report the state of the privacy controls.

Consent enforcement switches on per purpose when its wording is published, so
a deployment can be running with some purposes unenforced. That is a
legitimate intermediate state and an illegitimate permanent one, so it is
reported rather than left to be discovered.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.privacy.models import ConsentPurpose, ErasureRequest, ErasureState, RetentionPolicy
from apps.privacy.services import privacy_service


class Command(BaseCommand):
    help = "Report which privacy controls are configured and which are not."

    def handle(self, *args, **options) -> None:
        problems: list[str] = []

        self.stdout.write("Consent")
        unconfigured = privacy_service.unconfigured_purposes()
        for purpose in ConsentPurpose.values:
            document = privacy_service.current_document(purpose)
            if document is None:
                self.stdout.write(f"  {purpose:<16} NOT PUBLISHED - not enforced")
            else:
                essential = " (essential)" if document.is_essential else ""
                self.stdout.write(
                    f"  {purpose:<16} v{document.version} published - enforced{essential}"
                )
        if unconfigured:
            problems.append(
                f"{len(unconfigured)} consent purpose(s) have no published wording, so "
                f"no agreement is being asked for or checked: {', '.join(unconfigured)}. "
                f"Run: manage.py seed_consent"
            )

        self.stdout.write("\nRetention")
        policies = RetentionPolicy.objects.filter(is_active=True)
        if not policies.exists():
            problems.append(
                "No retention policies are configured, so nothing is ever "
                "scheduled for removal. Run: manage.py apply_retention --seed"
            )
        for policy in policies:
            action = "delete" if policy.hard_delete else "review"
            self.stdout.write(
                f"  {policy.category:<18} {policy.retain_days:>5}d  {action}"
            )

        self.stdout.write("\nErasure")
        open_requests = ErasureRequest.objects.filter(
            state__in=[ErasureState.REQUESTED, ErasureState.UNDER_REVIEW]
        ).count()
        self.stdout.write(f"  {open_requests} request(s) awaiting a decision")
        if open_requests:
            problems.append(
                f"{open_requests} erasure request(s) are waiting on a person. "
                f"These are time-bound rights; they should not sit."
            )

        self.stdout.write("")
        if problems:
            self.stdout.write("Needs attention:")
            for problem in problems:
                self.stdout.write(f"  - {problem}")
        else:
            self.stdout.write("All privacy controls are configured.")
