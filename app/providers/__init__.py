# app/providers/__init__.py

from app.providers.openai_provider    import OPENAI_CONFIG
from app.providers.anthropic_provider import ANTHROPIC_CONFIG
from app.providers.ollama_provider    import OLLAMA_CONFIG
from app.schemas.provider import ProviderConfig

PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    "openai":    OPENAI_CONFIG,
    "anthropic": ANTHROPIC_CONFIG,
    "ollama":    OLLAMA_CONFIG,
}

def get_provider(name: str) -> ProviderConfig:
    if name not in PROVIDER_REGISTRY:
        raise ValueError(f"Unknown provider: {name}")
    return PROVIDER_REGISTRY[name]