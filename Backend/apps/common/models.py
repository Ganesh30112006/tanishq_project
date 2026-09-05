"""Abstract model bases shared across apps.

Design rules enforced here:
* every externally-referenced row carries an opaque ``public_id`` so integer
  primary keys are never exposed to clients (spec section 42);
* ``created_at`` / ``updated_at`` are always present;
* ``VersionedModel`` provides optimistic locking for rows that must not be
  clobbered by concurrent writers (spec section 8).
"""
from __future__ import annotations

import uuid

from django.db import models

from apps.common.errors import OptimisticLockError


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublicIdModel(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    class Meta:
        abstract = True


class UUIDTimeStampedModel(PublicIdModel, TimeStampedModel):
    class Meta:
        abstract = True


class VersionedModel(UUIDTimeStampedModel):
    """Adds an integer ``version`` that must be supplied on update. Use
    :meth:`save_checked` (or ``update()`` with a ``version=`` filter) to get a
    conflict instead of a lost write."""

    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True

    def save_checked(self, *, expected_version: int | None = None, **kwargs: object) -> None:
        if self.pk is None or expected_version is None:
            super().save(**kwargs)  # type: ignore[arg-type]
            return
        updated = (
            type(self)
            .objects.filter(pk=self.pk, version=expected_version)
            .update(version=expected_version + 1)
        )
        if updated == 0:
            raise OptimisticLockError()
        self.version = expected_version + 1
        super().save(update_fields=None, **kwargs)  # type: ignore[arg-type]


class AppendOnlyModel(UUIDTimeStampedModel):
    """Rows may be created but never updated or deleted through the ORM. Used
    for audit and historical clinical observations (spec sections 8, 41, 44)."""

    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is not None and not kwargs.get("force_insert"):
            raise OptimisticLockError(
                "This record is append-only and cannot be modified.",
                code="APPEND_ONLY",
            )
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def delete(self, *args: object, **kwargs: object) -> None:
        raise OptimisticLockError(
            "This record is append-only and cannot be deleted.", code="APPEND_ONLY"
        )
