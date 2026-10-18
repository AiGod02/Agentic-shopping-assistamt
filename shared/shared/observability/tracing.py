"""
OpenTelemetry Tracing — auto-instrumentation with graceful fallback.

When OTel dependencies or collector are unavailable, tracing is silently disabled.
"""

from __future__ import annotations

from shared.observability.logging import get_logger

logger = get_logger(__name__)

_tracing_available = False

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    _tracing_available = True
except ImportError:
    logger.warning("opentelemetry_not_installed_tracing_disabled")


def setup_tracing(
    service_name: str,
    otlp_endpoint: str = "http://localhost:4317",
    environment: str = "development",
):
    """Initialize OpenTelemetry tracing — returns None if unavailable."""
    if not _tracing_available:
        return None

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        resource = Resource.create({
            "service.name": service_name,
            "service.version": "0.1.0",
            "deployment.environment": environment,
        })
        provider = TracerProvider(resource=resource)
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        trace.set_tracer_provider(provider)
        logger.info("tracing_initialized", endpoint=otlp_endpoint)
        return provider
    except Exception as e:
        logger.warning("tracing_setup_failed_continuing_without", error=str(e))
        return None


def instrument_fastapi(app, tracer_provider=None) -> None:
    if not _tracing_available or tracer_provider is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=tracer_provider, excluded_urls="health,ready,metrics",
        )
    except Exception as e:
        logger.warning("fastapi_instrumentation_failed", error=str(e))


def instrument_sqlalchemy(engine, tracer_provider=None) -> None:
    if not _tracing_available or tracer_provider is None:
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument(
            engine=engine.sync_engine, tracer_provider=tracer_provider,
        )
    except Exception as e:
        logger.warning("sqlalchemy_instrumentation_failed", error=str(e))


def instrument_redis(tracer_provider=None) -> None:
    if not _tracing_available or tracer_provider is None:
        return
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument(tracer_provider=tracer_provider)
    except Exception as e:
        logger.warning("redis_instrumentation_failed", error=str(e))


def instrument_httpx(tracer_provider=None) -> None:
    if not _tracing_available or tracer_provider is None:
        return
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)
    except Exception as e:
        logger.warning("httpx_instrumentation_failed", error=str(e))


def get_tracer(name: str):
    if _tracing_available:
        from opentelemetry import trace
        return trace.get_tracer(name)
    # Return a no-op tracer stub
    return _NoOpTracer()


class _NoOpTracer:
    """Stub tracer when OTel is not available."""
    def start_span(self, *args, **kwargs):
        return _NoOpSpan()
    def start_as_current_span(self, *args, **kwargs):
        import contextlib
        return contextlib.nullcontext(_NoOpSpan())


class _NoOpSpan:
    def set_attribute(self, *args, **kwargs): pass
    def set_status(self, *args, **kwargs): pass
    def record_exception(self, *args, **kwargs): pass
    def end(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
