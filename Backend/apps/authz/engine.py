"""Resource-level authorization engine.

RBAC (``apps.accounts.permissions``) answers "may this role do this kind of
thing?". This engine answers the rest of the tuple from spec section 6::

    ROLE + PERMISSION + RESOURCE + RELATIONSHIP + ACTION  ->  ALLOW / DENY

Every decision is explicit and default-deny: if no registered policy claims a
resource, access is denied. Authorization is evaluated *before* data is
returned - callers use :func:`authorize` / scoped querysets, never
"fetch broad then filter" (spec section 6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from apps.audit.services import ACCESS_DENIED, audit_service
from apps.common.errors import AccessDenied


class Action:
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    VALIDATE = "validate"
    PROCESS = "process"
    REQUEST_RISK = "request_risk"
    USE_AI = "use_ai"


@dataclass(slots=True)
class AccessRequest:
    actor: Any
    action: str
    resource: Any
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    policy: str
    reason: str = ""

    @classmethod
    def allow(cls, policy: str, reason: str = "") -> Decision:
        return cls(True, policy, reason)

    @classmethod
    def deny(cls, policy: str, reason: str = "") -> Decision:
        return cls(False, policy, reason)


class ResourcePolicy(Protocol):
    name: str

    def handles(self, resource: Any) -> bool: ...

    def decide(self, request: AccessRequest) -> Decision: ...


class PolicyEngine:
    def __init__(self) -> None:
        self._policies: list[ResourcePolicy] = []

    def register(self, policy: ResourcePolicy) -> None:
        self._policies.append(policy)

    def clear(self) -> None:  # test helper
        self._policies.clear()

    def evaluate(self, actor: Any, action: str, resource: Any, **context: Any) -> Decision:
        if actor is None or not getattr(actor, "is_authenticated", False):
            return Decision.deny("engine", "unauthenticated")

        request = AccessRequest(actor=actor, action=action, resource=resource, context=context)
        for policy in self._policies:
            if policy.handles(resource):
                return policy.decide(request)
        return Decision.deny("engine", "no policy handles this resource type")


engine = PolicyEngine()


def authorize(actor: Any, action: str, resource: Any, *, audit: bool = True, **context: Any) -> None:
    """Raise :class:`AccessDenied` unless ``actor`` may perform ``action`` on
    ``resource``. Denials are recorded in the audit trail."""
    decision = engine.evaluate(actor, action, resource, **context)
    if decision.allowed:
        return
    if audit:
        audit_service.denied(
            ACCESS_DENIED,
            actor=actor,
            resource=resource if hasattr(resource, "_meta") else None,
            reason=f"{action}: {decision.reason}"[:255],
            metadata={"action": action, "policy": decision.policy},
        )
    raise AccessDenied(details={"action": action, "reason": decision.reason})


def is_allowed(actor: Any, action: str, resource: Any, **context: Any) -> bool:
    return engine.evaluate(actor, action, resource, **context).allowed
