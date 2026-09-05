"""Service-layer primitives.

Business logic lives in explicit service objects, never in views, serializers
or uncontrolled signals (spec sections 4, 55, 56). ``ServiceResult`` gives
those services a uniform, inspectable return type so a caller can always tell
the difference between "done", "blocked - safe outcome" and "error".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class ServiceResult(Generic[T]):
    ok: bool
    value: T | None = None
    code: str | None = None
    message: str = ""
    details: dict[str, object] = field(default_factory=dict)

    @classmethod
    def success(cls, value: T | None = None, *, message: str = "") -> "ServiceResult[T]":
        return cls(ok=True, value=value, message=message)

    @classmethod
    def blocked(
        cls,
        code: str,
        message: str,
        *,
        value: T | None = None,
        details: dict[str, object] | None = None,
    ) -> "ServiceResult[T]":
        """A deliberate, safe non-completion (e.g. INSUFFICIENT_DATA).

        ``value`` may still carry a record that was persisted for traceability
        (for a risk request, the BLOCKED assessment row)."""
        return cls(ok=False, value=value, code=code, message=message, details=details or {})

    @property
    def failed(self) -> bool:
        return not self.ok


class BaseService:
    """Marker base class. Concrete services should be small and single-purpose,
    take their dependencies explicitly, and open their own transactions."""
