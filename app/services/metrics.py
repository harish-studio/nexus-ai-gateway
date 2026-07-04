# app/services/metrics.py
"""
Prometheus metrics for nexus-ai-gateway.

All metric objects are module-level singletons — initialised once per
process. Import record_request() in chat.py to update counters after
each completed request.

Metrics server runs on port 9090 (separate from the API on 8000):
- Keeps operational internals off the public API surface
- Follows standard Prometheus scraper conventions (no auth needed)
- Allows Cloud Run ingress to expose 8000 publicly, 9090 internally

Production scraping: configure Prometheus with:
    static_configs:
      - targets: ['<service>:9090']
"""

import logging
import threading
from wsgiref.simple_server import WSGIRequestHandler, make_server

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    make_wsgi_app,
    REGISTRY,
)

from app.schemas.audit import AuditRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

REQUESTS_TOTAL = Counter(
    "nexus_requests_total",
    "Total gateway requests",
    ["provider", "risk_tier", "cache_hit"],
)

REQUEST_LATENCY = Histogram(
    "nexus_request_latency_seconds",
    "Request latency in seconds",
    ["provider"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

COST_TOTAL = Counter(
    "nexus_cost_usd_total",
    "Total cost in USD by provider",
    ["provider"],
)

PII_REJECTIONS_TOTAL = Counter(
    "nexus_pii_rejections_total",
    "PII-rejected requests",
    ["stage"],  # "request" or "response"
)

FALLBACK_TOTAL = Counter(
    "nexus_fallback_total",
    "Fallback chain activations",
    ["from_provider", "to_provider"],
)

RATE_LIMIT_HITS_TOTAL = Counter(
    "nexus_rate_limit_hits_total",
    "Rate limit ceiling hits",
)

CACHE_HIT_RATIO = Gauge(
    "nexus_cache_hit_ratio",
    "Rolling cache hit ratio (hits / total requests)",
)

AUDIT_WRITES_TOTAL = Counter(
    "nexus_audit_writes_total",
    "Audit log write attempts",
    ["status"],  # "success" or "failed"
)

EU_AI_ACT_CLASSIFICATIONS_TOTAL = Counter(
    "nexus_eu_ai_act_classifications_total",
    "EU AI Act risk tier classifications",
    ["tier"],  # "minimal", "limited", "high", "unacceptable"
)

# ---------------------------------------------------------------------------
# Rolling cache hit ratio tracking
# ---------------------------------------------------------------------------

_cache_hits = 0
_cache_total = 0
_ratio_lock = threading.Lock()


def _update_cache_ratio(cache_hit: bool) -> None:
    global _cache_hits, _cache_total
    with _ratio_lock:
        _cache_total += 1
        if cache_hit:
            _cache_hits += 1
        ratio = _cache_hits / _cache_total if _cache_total > 0 else 0.0
        CACHE_HIT_RATIO.set(ratio)


# ---------------------------------------------------------------------------
# Main recording function — called from chat.py after each request
# ---------------------------------------------------------------------------

def record_request(record: AuditRecord) -> None:
    """
    Updates all Prometheus counters from a completed AuditRecord.
    Called synchronously after audit write in chat.py.
    Never raises — metric failure must not affect the response path.
    """
    try:
        REQUESTS_TOTAL.labels(
            provider=record.provider,
            risk_tier=record.risk_tier,
            cache_hit=str(record.cache_hit).lower(),
        ).inc()

        REQUEST_LATENCY.labels(
            provider=record.provider,
        ).observe(record.latency_ms / 1000)

        COST_TOTAL.labels(
            provider=record.provider,
        ).inc(record.cost_usd)

        EU_AI_ACT_CLASSIFICATIONS_TOTAL.labels(
            tier=record.risk_tier,
        ).inc()

        if record.fallback_from:
            FALLBACK_TOTAL.labels(
                from_provider=record.fallback_from,
                to_provider=record.provider,
            ).inc()

        _update_cache_ratio(record.cache_hit)

    except Exception as e:
        logger.warning("Failed to record metrics: %s", str(e))


def record_pii_rejection(stage: str) -> None:
    """
    Records a PII rejection event.
    stage: "request" (ingress blocked) or "response" (egress blocked).
    Called from chat.py at the point of rejection.
    """
    try:
        PII_REJECTIONS_TOTAL.labels(stage=stage).inc()
    except Exception as e:
        logger.warning("Failed to record PII rejection metric: %s", str(e))


def record_audit_write(success: bool) -> None:
    """
    Records audit log write outcome.
    Called from audit_service.py after each write attempt.
    """
    try:
        AUDIT_WRITES_TOTAL.labels(
            status="success" if success else "failed"
        ).inc()
    except Exception as e:
        logger.warning("Failed to record audit write metric: %s", str(e))


def record_rate_limit_hit() -> None:
    """Records a rate limit ceiling hit. Called from the slowapi handler."""
    try:
        RATE_LIMIT_HITS_TOTAL.inc()
    except Exception as e:
        logger.warning("Failed to record rate limit metric: %s", str(e))


# ---------------------------------------------------------------------------
# Metrics server — runs on port 9090 in a background thread
# ---------------------------------------------------------------------------

class _SilentHandler(WSGIRequestHandler):
    """Suppresses per-request log lines from the WSGI metrics server."""
    def log_message(self, format, *args):  # noqa: A002
        pass


def start_metrics_server(port: int = 9090) -> None:
    """
    Starts the Prometheus metrics server on a background daemon thread.
    Daemon thread ensures it shuts down automatically when the main
    process exits — no explicit teardown needed.

    Called once from app/main.py lifespan startup.
    """
    metrics_app = make_wsgi_app()

    def _serve():
        try:
            httpd = make_server("", port, metrics_app, handler_class=_SilentHandler)
            logger.info("Metrics server started on port %d", port)
            httpd.serve_forever()
        except Exception as e:
            logger.warning("Metrics server failed to start: %s", str(e))

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()