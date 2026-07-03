# app/providers/anthropic_provider.py
import httpx
from app.schemas.provider import ProviderConfig
from app.config.settings import settings
ANTHROPIC_CONFIG = ProviderConfig(
    name                = "anthropic",
    default_model       = "claude-sonnet-4-6",
    api_key_env_var     = "ANTHROPIC_API_KEY",
    priority=3, # secondary to OpenAI (lower priority — higher number)
    max_context_tokens  = 1_000_000, # 200k tokens is a reasonable limit 
)

async def health_check() -> bool:
    # Anthropic has no public /models endpoint — use a minimal
    # completion call with max_tokens=1 as the liveness probe
    try:
        # Ensure API key is present and all header values are strings
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            return False

        headers = {
            "x-api-key": str(api_key),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json={
                    "model": "claude-haiku-4-5",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )
        return r.status_code < 500
    except Exception:
        return False
