"""Publish the consent wording.

Publishing a purpose is what turns enforcement on for it (see
``PrivacyService.enforce_if_published``), so this is a deliberate step, not a
migration. The text below is a starting point written in plain Indian English;
it must be reviewed by whoever is accountable for privacy in the deployment
before real patients see it.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.privacy.models import ConsentDocument, ConsentPurpose

VERSION = "1.0"

DOCUMENTS: list[dict] = [
    {
        "purpose": ConsentPurpose.CARE,
        "is_essential": True,
        "body": (
            "We keep a health record for you so that the doctors treating you "
            "can see your history, your test results and your medicines. "
            "Without this we cannot provide care, so this one cannot be turned "
            "off while your record is open. If you no longer want us to hold "
            "your record, you can ask us to erase it."
        ),
    },
    {
        "purpose": ConsentPurpose.RISK_ANALYSIS,
        "is_essential": False,
        "body": (
            "We can use the readings already saved in your record to work out "
            "an estimate of your heart risk. It is only an estimate from a "
            "computer model, it is not a diagnosis, and a doctor still has to "
            "look at it. You can turn this off at any time and it will not "
            "affect your treatment."
        ),
    },
    {
        "purpose": ConsentPurpose.AI_ASSISTANCE,
        "is_essential": False,
        "body": (
            "We can use a computer program to write a short summary of what is "
            "already in your record, so that your doctor can read it quickly. "
            "The program only reads your own record. It does not add anything "
            "new and it does not make decisions about your care. You can turn "
            "this off at any time."
        ),
    },
    {
        "purpose": ConsentPurpose.RESEARCH,
        "is_essential": False,
        "body": (
            "We can use your readings for research to improve care, after "
            "removing your name, your date of birth and anything else that "
            "could identify you. Nobody doing the research will know the "
            "readings are yours. This is entirely your choice and saying no "
            "will not affect your treatment in any way."
        ),
    },
    {
        "purpose": ConsentPurpose.COMMUNICATIONS,
        "is_essential": False,
        "body": (
            "We can send you reminders and messages about your appointments, "
            "your reports and anything your doctor wants you to know. You can "
            "turn this off at any time. Urgent safety messages will still "
            "reach you."
        ),
    },
]


class Command(BaseCommand):
    help = "Publish the consent wording. Publishing a purpose enables consent checks for it."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--doc-version", default=VERSION, dest="doc_version")

    def handle(self, *args, **options) -> None:
        version = options["doc_version"]
        created = 0
        for spec in DOCUMENTS:
            exists = ConsentDocument.objects.filter(
                purpose=spec["purpose"], version=version
            ).exists()
            if exists:
                self.stdout.write(f"  {spec['purpose']} v{version} already published")
                continue
            # Append-only: a change in wording is a new version, never an edit.
            ConsentDocument.objects.create(
                purpose=spec["purpose"],
                version=version,
                body=spec["body"],
                is_essential=spec["is_essential"],
            )
            created += 1
            self.stdout.write(f"  published {spec['purpose']} v{version}")

        self.stdout.write(
            f"\n{created} document(s) published. Consent is now enforced for every "
            f"published purpose."
        )
