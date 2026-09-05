from __future__ import annotations

import pytest

from apps.audit.models import AuditLog
from apps.audit.services import audit_service
from apps.common.errors import OptimisticLockError

pytestmark = pytest.mark.django_db


def test_audit_rows_cannot_be_mutated_or_deleted():
    row = audit_service.record("test.action", metadata={"k": "v"})

    row.reason = "tampered"
    with pytest.raises(OptimisticLockError):
        row.save()

    with pytest.raises(OptimisticLockError):
        row.delete()

    assert AuditLog.objects.get(pk=row.pk).reason == ""


def test_audit_scrubs_clinical_looking_metadata_keys():
    row = audit_service.record("test.action", metadata={"glucose_value": 5.4, "count": 3})
    assert row.metadata["glucose_value"] == "[redacted]"
    assert row.metadata["count"] == 3
