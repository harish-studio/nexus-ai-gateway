# app/providers/__init__.py

from app.providers.openai_provider    import OPENAI_CONFIG
from app.providers.anthropic_provider import ANTHROPIC_CONFIG
from app.providers.ollama_provider    import OLLAMA_CONFIG
from app.providers.nvidia_nim_provider import NVIDIA_NIM_CONFIG
from app.schemas.provider import ProviderConfig

PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    "openai":    OPENAI_CONFIG,
    "anthropic": ANTHROPIC_CONFIG,
    "ollama_chat": OLLAMA_CONFIG,
    "nvidia_nim":  NVIDIA_NIM_CONFIG, 
}

def get_provider(name: str) -> ProviderConfig:
    if name not in PROVIDER_REGISTRY:
        raise ValueError(f"Unknown provider: {name}")
    return PROVIDER_REGISTRY[name]