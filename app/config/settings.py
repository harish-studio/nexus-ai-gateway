# app/config/settings.py

import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    OPENAI_API_KEY: Optional[str] = Field(default=None)
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None)
    NVIDIA_NIM_API_KEY: Optional[str] = Field(default=None) 
    OLLAMA_BASE_URL: Optional[str] = Field(default='http://host.docker.internal:11434')
    POSTGRES_URL: Optional[str] = Field(default=None)
    REDIS_URL: Optional[str] = Field(default=None)
    ENVIRONMENT: Optional[str] = Field(default='development')

settings = Settings()
