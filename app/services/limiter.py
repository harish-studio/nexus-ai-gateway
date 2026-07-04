# app/services/limiter.py
"""
Shared slowapi Limiter instance.

Defined here (not in main.py) to avoid circular imports:
main.py imports chat.py, chat.py needs the limiter,
so limiter must live in a module neither imports the other.
"""

import os

from slowapi import Limiter

from app.services.auth import get_api_key_for_ratelimit


limiter = Limiter(
    key_func=get_api_key_for_ratelimit,
    storage_uri=os.getenv("REDIS_URL", "redis://redis:6379/0"),
)