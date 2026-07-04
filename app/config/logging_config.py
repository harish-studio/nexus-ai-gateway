# app/config/logging_config.py
"""
Logging configuration for nexus-ai-gateway.

JSON format in production (ENVIRONMENT=production) for CloudWatch/
Cloud Logging ingestion. Plain text in development for readability.

Usage — call once at startup in app/main.py:
    from app.core.logging_config import configure_logging
    configure_logging()
"""

import logging
import os
import sys


class _JsonFormatter(logging.Formatter):
    """
    Minimal JSON log formatter — no third-party dependency.
    Produces one JSON object per line, compatible with CloudWatch
    Logs Insights and Google Cloud Logging structured log format.
    """

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level":     record.levelname,
            "logger":    record.name,
            "message":   record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    """
    Configures root logger based on ENVIRONMENT env var.
    - production  → JSON, WARNING level (reduce noise in log pipelines)
    - development → plain text, INFO level (human-readable in docker logs)
    """
    environment = os.getenv("ENVIRONMENT", "development").lower()
    is_production = environment == "production"

    level = logging.WARNING if is_production else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if is_production:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        ))

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any handlers already attached (e.g. uvicorn's default handler)
    # to avoid duplicate log lines
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party loggers regardless of environment
    for noisy in ("uvicorn.access", "httpx", "httpcore", "litellm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)