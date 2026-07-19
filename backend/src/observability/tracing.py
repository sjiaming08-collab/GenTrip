"""OpenTelemetry setup and safe trace-context helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ..config import settings

_provider_configured = False
_exporter_configured = False
_instrumented_apps: set[int] = set()


def configure_tracing(service_name: str | None = None) -> None:
    """Configure an SDK provider once; export only when an endpoint is configured."""
    global _provider_configured, _exporter_configured
    provider = trace.get_tracer_provider()
    if not _provider_configured:
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name or settings.otel_service_name}))
            trace.set_tracer_provider(provider)
        _provider_configured = True

    endpoint = settings.otel_exporter_otlp_traces_endpoint.strip()
    if endpoint and not _exporter_configured and isinstance(provider, TracerProvider):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        _exporter_configured = True


def instrument_fastapi(app: Any) -> None:
    configure_tracing("gentrip-api")
    app_id = id(app)
    if app_id in _instrumented_apps:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
    _instrumented_apps.add(app_id)


def inject_trace_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def extract_trace_context(carrier: object) -> context.Context | None:
    if not isinstance(carrier, Mapping):
        return None
    normalized = {str(key): str(value) for key, value in carrier.items()}
    return propagate.extract(normalized)


def start_plan_run_span(initial: dict[str, Any], *, tenant_id: str) -> tuple[trace.Span, object, str]:
    parent_context = extract_trace_context(initial.get("_trace_context"))
    span = trace.get_tracer("gentrip.runtime").start_span("gentrip.plan_run", context=parent_context)
    span.set_attribute("gentrip.run_id", str(initial.get("run_id", "")))
    span.set_attribute("gentrip.tenant_id", tenant_id)
    span.set_attribute("gentrip.execution_mode", settings.runtime_execution_mode)
    token = context.attach(trace.set_span_in_context(span))
    trace_id = f"{span.get_span_context().trace_id:032x}"
    return span, token, trace_id


def finish_plan_run_span(span: trace.Span, token: object, *, status: str, phase_count: int, token_usage: dict[str, int]) -> None:
    span.set_attribute("gentrip.run_status", status)
    span.set_attribute("gentrip.phase_count", phase_count)
    span.set_attribute("gen_ai.usage.input_tokens", token_usage.get("prompt_tokens", 0))
    span.set_attribute("gen_ai.usage.output_tokens", token_usage.get("completion_tokens", 0))
    context.detach(token)
    span.end()
