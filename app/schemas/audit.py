# app/schemas/audit.py

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AuditRecord(BaseModel):
    """
    Immutable record of a single gateway request.
    Written synchronously before the response is returned to the caller —
    guarantees every request is audited regardless of client behaviour.

    Production upgrade path: replace synchronous write with a Redis Streams
    consumer for throughput >1,000 req/min. See SCALING.md.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    request_id:      str      = Field(default_factory=lambda: str(uuid4()))
    timestamp:       datetime = Field(
                         default_factory=lambda: datetime.now(timezone.utc)
                     )  # default_factory — evaluated per instance, not at import time
    user_id:         str
    session_id:      str

    # Governance — required, always set from ClassificationResult.tier
    risk_tier:       str          # "minimal" | "limited" | "high" | "unacceptable"
    pii_entities:    list[str] = Field(default_factory=list)

    # Routing
    requested_model: str
    actual_model:    str
    provider:        str
    fallback_used:   bool = False
    fallback_from:   str | None = None   # provider originally intended before fallback

    # Economics
    input_tokens:    int
    output_tokens:   int
    cost_usd:        float
    latency_ms:      int
    cache_hit:       bool

    # Integrity
    response_hash:   str    # SHA-256 of full response content
    content_preview: str    # first 200 chars — GDPR-safer than storing full content