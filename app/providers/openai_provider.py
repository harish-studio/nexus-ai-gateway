# app/providers/openai_provider.py

import httpx
from app.schemas.provider import ProviderConfig
from app.config.settings import settings

OPENAI_CONFIG = ProviderConfig(
    name                = "openai",
    default_model       = "gpt-5.4",
    api_key_env_var     = "OPENAI_API_KEY",
    priority            = 2,
    max_context_tokens  = 400_000,
)

async def health_check() -> bool:
    try:
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            return False
        
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return r.status_code == 200
    except Exception:
        return False
