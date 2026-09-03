# app/schemas/request.py

from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from enum import Enum
from uuid import uuid4

class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1, max_length=32_000)

class ModelPreference(str, Enum):
    AUTO     = "auto"      # router decides
    FAST     = "fast"      # cheapest capable model
    ACCURATE = "accurate"  # best model regardless of cost
    LOCAL    = "local"     # Ollama only (PII / air-gap)
    NVIDIA   = "nvidia"    # explicit NIM routing — Nemotron
    NVIDIA_LOCAL = "nvidia_local"

class ChatRequest(BaseModel):
    messages:          list[Message] = Field(..., min_length=1)
    model_preference:  ModelPreference = ModelPreference.AUTO
    max_tokens:        int = Field(default=1024, ge=1, le=4096)
    stream:            bool = False
    user_id:           str = Field(..., min_length=1, max_length=128)
    session_id:        str = Field(default_factory=lambda: str(uuid4()))
    metadata:          dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)
