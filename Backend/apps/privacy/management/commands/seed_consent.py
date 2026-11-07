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

#: 2.0: the 1.0 wording described doctors reading the record and checking the
#: estimate. There is no doctor in this product, so people were agreeing to
#: something that does not happen. Documents are append-only: 1.0 stays on
#: record for anyone who agreed to it.
#: 3.0: says what has not been proven: accuracy is unmeasured, and the heart model
#: has not been tested on Indian people and may show too low a risk.
VERSION = "3.0"

DOCUMENTS: list[dict] = [
    {
        "purpose": ConsentPurpose.CARE,
        "is_essential": True,
        "body": (
            "We keep your account and the reports you upload, so that you can "
            "see them and our AI can read them for you. Without this the app "
            "cannot work, so this one cannot be turned off while you have an "
            "account. If you no longer want us to keep your data, you can ask "
            "us to delete it in Settings."
        ),
    },
    {
        "purpose": ConsentPurpose.RISK_ANALYSIS,
        "is_essential": False,
        "body": (
            "We can use the readings saved in your record to work out an "
            "estimate of your heart risk. It is only an estimate from a "
            "computer model. It is not a diagnosis, no doctor checks it, and "
            "the model was built on people in the US and has not been tested on "
            "Indian people, so it may show your risk as lower than it really is. "
            "Please show it to a "
            "doctor before you act on it. You can turn this off at any time."
        ),
    },
    {
        "purpose": ConsentPurpose.AI_ASSISTANCE,
        "is_essential": False,
        "body": (
            "Our AI can read the reports you upload and explain in simple words "
            "what they show, including possible conditions the results may "
            "point to. It can be wrong, it never gives a diagnosis, and no "
            "doctor checks what it says. We have not yet measured how accurate "
            "it is. Your reports are read on our own "
            "systems and are not sent to any outside AI company. You can turn "
            "this off at any time."
        ),
    },
    {
        "purpose": ConsentPurpose.RESEARCH,
        "is_essential": False,
        "body": (
            "We can use your readings for research to improve CareSense, after "
            "removing your name, your date of birth and anything else that "
            "could identify you. Nobody doing the research will know the "
            "readings are yours. This is entirely your choice, and saying no "
            "changes nothing else in the app."
        ),
    },
    {
        "purpose": ConsentPurpose.COMMUNICATIONS,
        "is_essential": False,
        "body": (
            "We can send you messages about your reports, for example when our "
            "AI has finished reading one. You can turn this off at any time. "
            "Messages about your account's safety, such as a password reset you "
            "asked for, will still reach you."
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
