# app/schemas/response.py

from pydantic import BaseModel, Field, computed_field

class ChatResponse(BaseModel):
    request_id:    str
    content:       str
    model_used:    str          # actual model (post-fallback)
    provider:      str          # actual provider (post-fallback)
    input_tokens:  int
    output_tokens: int
    cost_usd:      float = Field(..., ge=0)
    latency_ms:    int
    cache_hit:     bool
    session_id:    str

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
    
