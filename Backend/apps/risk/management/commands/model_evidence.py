"""Show what is known - and what is not - about a registered model version.

The dossier is assembled by ``intelligence.ml_service.evidence`` and stored on
the version at registration. This command reads it back from the registry
rather than from the artifact directory, so what it prints is what the system
will actually judge an approval against, not what happens to be on disk.

Usage::

    python manage.py model_evidence --model cvd-nhanes-logreg --model-version 3.1.0
    python manage.py model_evidence --task cvd --gaps-only
"""
from __future__ import annotations

import textwrap

from django.core.management.base import BaseCommand, CommandError

from apps.risk.models import ModelVersion

MARK = {"answered": "answered  ", "partial": "PARTIAL   ",
        "unanswered": "UNANSWERED"}


class Command(BaseCommand):
    help = "Print the evidence dossier recorded for a model version."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--model", help="model_id, e.g. cvd-nhanes-logreg")
        # Not --version: Django's BaseCommand already owns that flag.
        parser.add_argument("--model-version", dest="model_version",
                            help="version, e.g. 3.1.0")
        parser.add_argument("--task", help="show the version currently backing this task")
        parser.add_argument(
            "--gaps-only", action="store_true",
            help="print only the questions that are not fully answered",
        )

    def handle(self, *args, **options) -> None:
        versions = ModelVersion.objects.all()
        if options.get("task"):
            versions = versions.filter(task=options["task"])
        if options.get("model"):
            versions = versions.filter(model_id=options["model"])
        if options.get("model_version"):
            versions = versions.filter(version=options["model_version"])
        version = versions.order_by("-created_at").first()
        if version is None:
            raise CommandError("No model version matches those filters.")

        dossier = version.evidence_dossier or {}
        self.stdout.write(f"{version.model_id}:{version.version}  "
                          f"[{version.lifecycle_state}]")
        if not dossier:
            self.stdout.write(self.style.WARNING(
                "No evidence dossier is recorded for this version. That is not "
                "the same as having no gaps - it means nothing is known about "
                "what is known. Run `python -m intelligence.ml_service.evidence "
                f"--version {version.version}` and re-register."
            ))
            return

        counts = dossier.get("status_counts", {})
        self.stdout.write(
            f"question set {dossier.get('questions_version')}   "
            f"answered {counts.get('answered', 0)}   "
            f"partial {counts.get('partial', 0)}   "
            f"unanswered {counts.get('unanswered', 0)}"
        )
        self.stdout.write("")

        for index, answer in enumerate(dossier.get("answers", []), start=1):
            if options["gaps_only"] and answer["status"] == "answered":
                continue
            style = (self.style.SUCCESS if answer["status"] == "answered"
                     else self.style.WARNING)
            self.stdout.write(style(
                f"{index:>3}. [{MARK.get(answer['status'], answer['status'])}] "
                f"{answer.get('question', answer.get('key', '?'))}"
            ))
            self.stdout.write(textwrap.fill(
                answer.get("answer", ""), width=76,
                initial_indent="      ", subsequent_indent="      ",
            ))
            if answer.get("to_answer_this"):
                self.stdout.write(textwrap.fill(
                    "What would answer it: " + answer["to_answer_this"], width=76,
                    initial_indent="      ", subsequent_indent="      ",
                ))
            self.stdout.write("")

        open_questions = version.open_evidence_questions()
        if open_questions:
            self.stdout.write(self.style.WARNING(
                "Approving this version for clinical review requires naming "
                "these gaps in the transition evidence: "
                + ", ".join(open_questions)
            ))
