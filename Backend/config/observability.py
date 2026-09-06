"""OpenTelemetry-compatible instrumentation.

Observability is optional. When ``OTEL_ENABLED`` is false (the default) none
of this runs and OpenTelemetry is not even imported, so the base install
stays lean. Enable it by installing the ``observability`` extra and setting
``OTEL_ENABLED=true`` plus an OTLP endpoint.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("caresense.observability")


def configure_observability() -> bool:
    """Wire up tracing for Django + outbound HTTP. Safe to call more than once."""
    if not _enabled():
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OTEL_ENABLED is set but opentelemetry packages are not installed.")
        return False

    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "caresense-django")})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    DjangoInstrumentor().instrument()
    logger.info("OpenTelemetry tracing configured.")
    return True


def _enabled() -> bool:
    return os.environ.get("OTEL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
