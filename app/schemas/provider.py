# app/schemas/provider.py

from pydantic import BaseModel

class ProviderConfig(BaseModel):
    name: str
    default_model: str
    api_key_env_var: str
    priority: int
    supports_streaming: bool = True
    max_context_tokens: int = 128_000


class RoutingDecision(BaseModel):
    provider: str
    chosen_model: str
    reason: str
    fallback_from: str | None = None