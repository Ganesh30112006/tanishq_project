from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.risk.models import ModelVersion, RiskModel


class Command(BaseCommand):
    help = "List registered model versions and which are active per task."

    def handle(self, *args, **options) -> None:
        active = {rm.task: rm for rm in RiskModel.objects.select_related("active_version")}
        for mv in ModelVersion.objects.order_by("task", "model_id", "version"):
            rm = active.get(mv.task)
            is_active = rm is not None and rm.is_enabled and rm.active_version_id == mv.pk
            flag = "ACTIVE" if is_active else mv.lifecycle_state
            auc = mv.validation_metrics.get("roc_auc", "-")
            self.stdout.write(f"[{flag:8}] {mv.task:12} {mv.model_id}:{mv.version}  roc_auc={auc}")
        if not ModelVersion.objects.exists():
            self.stdout.write("No model versions registered.")
