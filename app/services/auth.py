# app/services/auth.py
"""
API key authentication for nexus-ai-gateway.

Keys are stored in .env as a comma-separated list of key:label pairs:
    API_KEYS=nexus-key-demo-1:recruiter_1,nexus-key-demo-2:recruiter_2

The label is used as user_id in the audit log — each key's activity
is automatically separated without callers needing to pass a user ID.

Returns HTTP 401 with WWW-Authenticate: ApiKey on invalid/missing key,
following HTTP semantics: 401 = unauthenticated, 403 = unauthorised.
"""

import os
from functools import lru_cache
from fastapi import HTTPException, Security, Request
from fastapi.security import APIKeyHeader

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


@lru_cache(maxsize=1)
def _load_key_map() -> dict[str, str]:
    """
    Parses API_KEYS env var into {key: label} dict.
    Cached — keys are loaded once per process.
    Restart required to pick up new keys (consistent with .env behaviour
    throughout this project).

    Example:
        API_KEYS=nexus-key-demo-1:recruiter_1,nexus-key-demo-2:recruiter_2
        → {"nexus-key-demo-1": "recruiter_1", "nexus-key-demo-2": "recruiter_2"}
    """
    raw = os.getenv("API_KEYS", "")
    if not raw:
        return {}

    key_map: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            key, label = entry.split(":", 1)
            key_map[key.strip()] = label.strip()
        else:
            # Key with no label — use the key itself as the label
            key_map[entry] = entry

    return key_map


def validate_api_key(
    api_key: str | None = Security(_API_KEY_HEADER),
) -> str:
    """
    FastAPI Security dependency — validates the X-API-Key header.

    Returns the key's label (used as user_id in audit log) on success.
    Raises HTTP 401 with WWW-Authenticate header on failure.

    Usage:
        @router.post("/chat")
        async def chat(
            request: ChatRequest,
            user_label: str = Security(validate_api_key),
        ):
            ...
    """
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "missing_api_key",
                "message": "X-API-Key header is required.",
            },
            headers={"WWW-Authenticate": "ApiKey"},
        )

    key_map = _load_key_map()
    label = key_map.get(api_key)

    if label is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_api_key",
                "message": "The provided API key is not valid.",
            },
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return label

def get_api_key_for_ratelimit(request: Request) -> str:
    """
    slowapi key_func — rate limits per API key, not per IP.
    Called by slowapi internally, not as a FastAPI dependency.
    Falls back to client IP if header is absent (belt-and-braces).
    """
    return (
        request.headers.get("X-API-Key")
        or (request.client.host if request.client else "unknown")
    )