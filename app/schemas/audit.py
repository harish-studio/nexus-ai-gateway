# app/schemas/audit.py

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone
from uuid import uuid4

class AuditRecord(BaseModel):
    request_id:        str = Field(default_factory=lambda: str(uuid4()))
    timestamp:         datetime = Field(default=datetime.now(timezone.utc))
    user_id:           str
    session_id:        str
    # Governance fields (populated Day 4–5)
    risk_tier:         str = "unclassified"
    pii_entities:      list[str] = Field(default_factory=list)
    # Routing
    requested_model:   str
    actual_model:      str
    provider:          str
    fallback_used:     bool = False
    # Economics
    input_tokens:      int
    output_tokens:     int
    cost_usd:          float
    latency_ms:        int
    cache_hit:         bool
    # Integrity
    response_hash:     str   # SHA-256 of response content
    content:       str



    model_config = ConfigDict(frozen=True)   # immutable after creation

