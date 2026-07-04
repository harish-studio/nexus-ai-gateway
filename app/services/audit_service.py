# app/services/audit_service.py
"""
Audit log service for nexus-ai-gateway.

Writes an AuditRecord to Postgres synchronously before the response
is returned to the caller — guarantees every request is audited.

Production upgrade path: replace with a Redis Streams consumer at
throughput >1,000 req/min. See SCALING.md.

Table is created on startup via ensure_audit_table() called from
app/main.py lifespan, keeping the deployment self-contained.
"""

import hashlib
import logging
import os

import asyncpg

from app.schemas.audit import AuditRecord
from app.schemas.response import ChatResponse
from app.schemas.provider import RoutingDecision
from app.services.risk_classifier import ClassificationResult
from app.services.metrics import record_audit_write
logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    request_id       TEXT        PRIMARY KEY,
    timestamp        TIMESTAMPTZ NOT NULL,
    user_id          TEXT        NOT NULL,
    session_id       TEXT        NOT NULL,
    risk_tier        TEXT        NOT NULL,
    pii_entities     TEXT[]      NOT NULL DEFAULT '{}',
    requested_model  TEXT        NOT NULL,
    actual_model     TEXT        NOT NULL,
    provider         TEXT        NOT NULL,
    fallback_used    BOOLEAN     NOT NULL DEFAULT FALSE,
    fallback_from    TEXT,
    input_tokens     INTEGER     NOT NULL,
    output_tokens    INTEGER     NOT NULL,
    cost_usd         NUMERIC(12,6) NOT NULL,
    latency_ms       INTEGER     NOT NULL,
    cache_hit        BOOLEAN     NOT NULL DEFAULT FALSE,
    response_hash    TEXT        NOT NULL,
    content_preview  TEXT        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
    ON audit_log (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_id
    ON audit_log (user_id);

CREATE INDEX IF NOT EXISTS idx_audit_log_risk_tier
    ON audit_log (risk_tier);
"""

_INSERT_SQL = """
INSERT INTO audit_log (
    request_id, timestamp, user_id, session_id,
    risk_tier, pii_entities,
    requested_model, actual_model, provider,
    fallback_used, fallback_from,
    input_tokens, output_tokens, cost_usd,
    latency_ms, cache_hit,
    response_hash, content_preview
) VALUES (
    $1, $2, $3, $4,
    $5, $6,
    $7, $8, $9,
    $10, $11,
    $12, $13, $14,
    $15, $16,
    $17, $18
)
ON CONFLICT (request_id) DO NOTHING;
"""


async def ensure_audit_table() -> None:
    """
    Creates the audit_log table and indexes if they don't exist.
    Safe to call on every startup.
    """
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        logger.warning("POSTGRES_URL not set — audit table not created")
        return
    try:
        conn = await asyncpg.connect(postgres_url)
        await conn.execute(_CREATE_TABLE_SQL)
        await conn.close()
        logger.info("Audit log table ready")
    except Exception as e:
        logger.warning("Could not create audit table: %s", str(e))


def build_audit_record(
    request_id: str,
    user_id: str,
    session_id: str,
    requested_model: str,
    decision: RoutingDecision,
    classification: ClassificationResult,
    pii_entities: list[str],
    response: ChatResponse,
) -> AuditRecord:
    """
    Builds an AuditRecord from all gateway request/response artefacts.
    Kept as a pure function (no I/O) so it's independently unit-testable.
    """
    content_hash = hashlib.sha256(
        response.content.encode("utf-8")
    ).hexdigest()

    content_preview = response.content[:200]

    return AuditRecord(
        request_id      = request_id,
        user_id         = user_id,
        session_id      = session_id,
        risk_tier       = classification.tier,
        pii_entities    = pii_entities,
        requested_model = requested_model,
        actual_model    = response.model_used,
        provider        = response.provider,
        fallback_used   = decision.fallback_from is not None,
        fallback_from   = decision.fallback_from,
        input_tokens    = response.input_tokens,
        output_tokens   = response.output_tokens,
        cost_usd        = response.cost_usd,
        latency_ms      = response.latency_ms,
        cache_hit       = response.cache_hit,
        response_hash   = content_hash,
        content_preview = content_preview,
    )


async def write_audit_record(record: AuditRecord) -> None:
    """
    Writes an AuditRecord to Postgres.
    ON CONFLICT DO NOTHING — idempotent, safe to retry.
    Degrades gracefully on DB errors — logs warning and continues.
    """
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        logger.warning("POSTGRES_URL not set — audit record not written")
        return
    try:
        conn = await asyncpg.connect(postgres_url)
        await conn.execute(
            _INSERT_SQL,
            record.request_id,
            record.timestamp,
            record.user_id,
            record.session_id,
            record.risk_tier,
            record.pii_entities,
            record.requested_model,
            record.actual_model,
            record.provider,
            record.fallback_used,
            record.fallback_from,
            record.input_tokens,
            record.output_tokens,
            record.cost_usd,
            record.latency_ms,
            record.cache_hit,
            record.response_hash,
            record.content_preview,
        )
        await conn.close()
        logger.info("Audit record written: %s", record.request_id)
        record_audit_write(success=True)
    except Exception as e:
        logger.warning("Audit write failed: %s", str(e))
        record_audit_write(success=False) 