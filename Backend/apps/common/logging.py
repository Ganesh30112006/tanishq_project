"""Structured logging.

Emits one JSON object per line and attaches the request correlation id when
one is set. Formatters must never be handed sensitive medical content by
callers (spec section 41); this class only serializes what it is given.
"""
from __future__ import annotations

import datetime as dt
import json
import logging

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()) | {
    "message",
    "asctime",
}


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Correlation id, if the audit middleware set one for this request.
        try:
            from apps.audit.context import get_request_id

            request_id = get_request_id()
            if request_id:
                payload["request_id"] = request_id
        except Exception:  # pragma: no cover - logging must never raise
            pass

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            # Server-side operational logs are not the client-facing error
            # payload (apps.common.errors masks internals there per spec
            # section 43) - operators still need enough here to debug a 500
            # without re-running with DEBUG on.
            payload["exc_type"] = getattr(record.exc_info[0], "__name__", "Exception")
            payload["exc_message"] = str(record.exc_info[1])
            payload["exc_traceback"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)
