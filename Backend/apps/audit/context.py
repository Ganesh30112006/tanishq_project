"""Request-scoped context.

Uses :mod:`contextvars`, which are bound per request/task - never a shared
mutable module global (spec section 7). The audit middleware binds these at
the start of a request and clears them in a ``finally``.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "caresense_request_id", default=None
)
_actor_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "caresense_actor_id", default=None
)
_actor_label: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "caresense_actor_label", default=None
)
_client_ip: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "caresense_client_ip", default=None
)
_user_agent: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "caresense_user_agent", default=None
)


@dataclass(slots=True)
class RequestContext:
    request_id: str | None
    actor_id: str | None
    actor_label: str | None
    client_ip: str | None
    user_agent: str | None


def bind(
    *,
    request_id: str | None,
    actor_id: str | None = None,
    actor_label: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    _request_id.set(request_id)
    _actor_id.set(actor_id)
    _actor_label.set(actor_label)
    _client_ip.set(client_ip)
    _user_agent.set(user_agent)


def set_actor(actor_id: str | None, actor_label: str | None) -> None:
    _actor_id.set(actor_id)
    _actor_label.set(actor_label)


def clear() -> None:
    bind(request_id=None)


def get_request_id() -> str | None:
    return _request_id.get()


def current() -> RequestContext:
    return RequestContext(
        request_id=_request_id.get(),
        actor_id=_actor_id.get(),
        actor_label=_actor_label.get(),
        client_ip=_client_ip.get(),
        user_agent=_user_agent.get(),
    )
