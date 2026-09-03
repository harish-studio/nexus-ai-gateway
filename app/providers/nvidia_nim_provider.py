# app/providers/nvidia_nim_provider.py

import httpx
from app.schemas.provider import ProviderConfig
from app.config.settings import settings

NVIDIA_NIM_CONFIG = ProviderConfig(
    name               = "nvidia_nim",
    default_model      = "nvidia/nemotron-3.5-lightning-30b-a3b",
    api_key_env_var    = "NVIDIA_NIM_API_KEY",
    priority           = 3,  # tertiary — after OpenAI and Anthropic
    max_context_tokens = 131_072,  # 128k context window for this model
)

async def health_check() -> bool:
    # NIM hosted endpoints expose a standard /v1/models listing —
    # use it as the liveness probe (no token spend, no completion call)
    try:
        api_key = settings.NVIDIA_NIM_API_KEY
        if not api_key:
            return False

        headers = {
            "Authorization": f"Bearer {str(api_key)}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://integrate.api.nvidia.com/v1/models",
                headers=headers,
            )
        return r.status_code < 500
    except Exception:
        return False