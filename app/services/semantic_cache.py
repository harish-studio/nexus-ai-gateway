# app/services/semantic_cache.py
"""
Semantic cache for nexus-ai-gateway using Redis 8 vector search
and FastEmbed (BAAI/bge-small-en-v1.5, 384-dim ONNX).

Design decisions:
- Full conversation history embedded as one string — more accurate
  than last-message-only since context changes meaning.
- Cosine similarity threshold: 0.92 — catches paraphrases without
  false matches on loosely related questions.
- TTL: 24 hours — balances hit rate with freshness.
- High Risk requests are never cached — they must be re-evaluated
  fresh on every call for governance correctness.
- Cache miss on any Redis error — degrades gracefully without
  breaking the request path.

Reference: https://redis.io/docs/latest/develop/ai/search-and-query/vectors/
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
from functools import lru_cache
from typing import cast, Any
import numpy as np
from fastembed import TextEmbedding
from redis.asyncio import Redis
from redis.commands.search.field import TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VECTOR_DIM = 384                    # BAAI/bge-small-en-v1.5 output dimensions
SIMILARITY_THRESHOLD = 0.92         # cosine similarity — below this is a miss
CACHE_TTL_SECONDS = 86_400          # 24 hours
INDEX_NAME = "nexus_semantic_cache"
DOC_PREFIX = "cache:"
MODEL_NAME = "BAAI/bge-small-en-v1.5"


# ---------------------------------------------------------------------------
# Embedding model — loaded once per process
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_embedding_model() -> TextEmbedding:
    """
    Initialises FastEmbed once per process.
    lru_cache avoids reloading the ONNX model on every request.
    Model is pre-downloaded into the Docker image at build time —
    see Dockerfile for FASTEMBED_CACHE_DIR configuration.
    """
    logger.info("Initialising FastEmbed model %s (one-time cold start)", MODEL_NAME)
    cache_dir = os.environ.get("FASTEMBED_CACHE_DIR", None)
    return TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=cache_dir,
    )


def _embed(text: str) -> np.ndarray:
    """Embeds text and returns a normalised float32 numpy array."""
    model = _get_embedding_model()
    vectors = list(model.embed([text]))
    return np.array(vectors[0], dtype=np.float32)


def _messages_to_text(messages: list[dict]) -> str:
    """
    Serialises full conversation history to a single string for embedding.
    Format: 'role: content\n' per turn — preserves ordering and speaker.
    """
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

async def ensure_index(redis: Redis) -> None:
    """
    Creates the vector index if it doesn't exist.
    Safe to call on every startup — checks before creating.
    Uses FLAT index (brute force) — sufficient for demo scale;
    switch to HNSW for production at >100k cached entries.
    """
    try:
        await redis.ft(INDEX_NAME).info()
        logger.debug("Redis vector index '%s' already exists", INDEX_NAME)
    except Exception:
        logger.info("Creating Redis vector index '%s'", INDEX_NAME)
        schema = [
            TagField("risk_tier"),
            VectorField(
                "embedding",
                "FLAT",
                {
                    "TYPE": "FLOAT32",
                    "DIM": VECTOR_DIM,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
        ]
        definition = IndexDefinition(
            prefix=[DOC_PREFIX],
            index_type=IndexType.HASH,
        )
        await redis.ft(INDEX_NAME).create_index(
            fields=schema,
            definition=definition,
        )


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

async def get_cached_response(
    redis: Redis,
    messages: list[dict],
) -> dict | None:
    """
    Looks up the cache for a semantically similar conversation.
    Returns the cached response dict on HIT, None on MISS.
    Degrades gracefully on Redis errors — returns None (treat as miss).
    """
    try:
        text = _messages_to_text(messages)
        vector = _embed(text)
        vector_bytes = vector.tobytes()

        # Cosine distance threshold — Redis stores distance not similarity,
        # so threshold is (1 - similarity) = 1 - 0.92 = 0.08
        distance_threshold = round(1 - SIMILARITY_THRESHOLD, 4)

        query = (
            Query(
                f"@embedding:[VECTOR_RANGE {distance_threshold} $vec]"
                "=>{$YIELD_DISTANCE_AS: vector_dist}"
            )
            .sort_by("vector_dist")
            .return_fields("response_json", "vector_dist")
            .dialect(2)
        )

        results = cast(
            Any,
            await redis.ft(INDEX_NAME).search(
                query,
                query_params={"vec": vector_bytes},
            ),
        )

        if results.total > 0:
            cached = results.docs[0]
            logger.info(
                "Cache HIT — cosine distance %.4f (threshold %.4f)",
                float(cached.vector_dist),
                distance_threshold,
            )
            return json.loads(cached.response_json)

        logger.debug("Cache MISS")
        return None

    except Exception as e:
        logger.warning("Cache lookup failed, treating as miss: %s", str(e))
        return None


async def store_response(
    redis: Redis,
    messages: list[dict],
    response_dict: dict,
    risk_tier: str,
) -> None:
    """
    Stores a response in the semantic cache.
    High Risk responses are never stored — they must be re-evaluated fresh.
    Degrades gracefully on Redis errors — logs warning and continues.
    """
    if risk_tier == "high":
        logger.debug(
            "Skipping cache storage for High Risk request — "
            "must be re-evaluated fresh for governance correctness"
        )
        return

    try:
        text = _messages_to_text(messages)
        vector = _embed(text)
        vector_bytes = vector.tobytes()

        # Use a hash of the text as the key suffix for deduplication
        
        key_suffix = hashlib.sha256(text.encode()).hexdigest()[:16]
        cache_key = f"{DOC_PREFIX}{key_suffix}"

        await redis.hset(
            cache_key,
            mapping={
                "embedding": vector_bytes,
                "response_json": json.dumps(response_dict),
                "risk_tier": risk_tier,
            },
        )
        await redis.expire(cache_key, CACHE_TTL_SECONDS)

        logger.info(
            "Stored response in cache (key: %s, TTL: %ds)",
            cache_key,
            CACHE_TTL_SECONDS,
        )

    except Exception as e:
        logger.warning("Cache storage failed, continuing without cache: %s", str(e))