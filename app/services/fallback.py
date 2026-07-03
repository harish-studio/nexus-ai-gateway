# app/services/fallback.py
"""
Fallback chain execution for nexus-ai-gateway.

Sits between chat.py (routing) and llm_client.py (execution).
Owns the ordered fallback sequence per ModelPreference and retries
on provider failure until a response is obtained or all options
are exhausted.

Design decisions:
- LOCAL falls back to cloud providers (OpenAI → Anthropic) rather
  than erroring immediately. Documented as interim behaviour pending
  the EU AI Act risk classifier (stage 7), which will introduce
  LOCAL_REQUIRED (hard no-fallback) vs LOCAL_PREFERRED (current).
- ACCURATE falls back to OpenAI flagship (gpt-5.4), not nano —
  preserving quality intent even in the fallback path.
- fallback_from is set on every RoutingDecision that results from
  a fallback, making the override auditable in the response and
  eventually in the audit log.
"""

import logging
from dataclasses import dataclass

from fastapi import HTTPException

from app.providers import get_provider
from app.schemas.provider import RoutingDecision
from app.schemas.request import ModelPreference
from app.schemas.response import ChatResponse
from app.services import llm_client

logger = logging.getLogger(__name__)


@dataclass
class FallbackCandidate:
    provider: str
    model: str  # explicit model, not just default — avoids surprise on ACCURATE fallback


def _build_chain(decision: RoutingDecision, preference: ModelPreference) -> list[FallbackCandidate]:
    """
    Returns the ordered fallback candidates for a given preference,
    excluding the provider that already failed (decision.provider).
    The first candidate in the list is always the original decision —
    execute() pops it and uses it as the primary attempt.
    """
    ollama   = get_provider("ollama")
    openai   = get_provider("openai")
    anthropic = get_provider("anthropic")

    chains: dict[ModelPreference, list[FallbackCandidate]] = {
        ModelPreference.LOCAL: [
            FallbackCandidate(ollama.name,    ollama.default_model),
            FallbackCandidate(openai.name,    openai.default_model),      # gpt-5.4
            FallbackCandidate(anthropic.name, anthropic.default_model),   # claude-sonnet-4-6
        ],
        ModelPreference.FAST: [
            FallbackCandidate(openai.name,    openai.default_model),      # gpt-5.4
            FallbackCandidate(anthropic.name, anthropic.default_model),   # claude-sonnet-4-6
            FallbackCandidate(ollama.name,    ollama.default_model),      # qwen3.5:4b
        ],
        ModelPreference.ACCURATE: [
            FallbackCandidate(anthropic.name, anthropic.default_model),   # claude-sonnet-4-6
            FallbackCandidate(openai.name,    openai.default_model),      # gpt-5.4 (flagship, not nano)
            FallbackCandidate(ollama.name,    ollama.default_model),      # last resort
        ],
        ModelPreference.AUTO: [
            # Priority order: Ollama(1) → OpenAI(2) → Anthropic(3)
            FallbackCandidate(ollama.name,    ollama.default_model),
            FallbackCandidate(openai.name,    openai.default_model),
            FallbackCandidate(anthropic.name, anthropic.default_model),
        ],
    }

    # Start the chain from the originally decided provider, not always
    # the chain head — e.g. ACCURATE may have been downgraded to OpenAI
    # by complexity scoring; the fallback should start from there.
    full_chain = chains[preference]
    start_index = next(
        (i for i, c in enumerate(full_chain) if c.provider == decision.provider),
        0,
    )
    return full_chain[start_index:]


async def execute(
    decision: RoutingDecision,
    preference: ModelPreference,
    messages: list[dict],
    max_tokens: int,
    request_id: str,
    session_id: str,
) -> ChatResponse:
    """
    Attempts the primary provider in the decision, then works through
    the fallback chain on any exception until a response is obtained
    or all candidates are exhausted.
    """
    chain = _build_chain(decision, preference)
    last_error: Exception | None = None

    for i, candidate in enumerate(chain):
        is_fallback = i > 0
        current_decision = RoutingDecision(
            provider=candidate.provider,
            chosen_model=candidate.model,
            reason=(
                f"Fallback attempt {i}: {candidate.provider}/{candidate.model} "
                f"after {last_error.__class__.__name__} on "
                f"{chain[i - 1].provider}"
            ) if is_fallback else decision.reason,
            fallback_from=chain[i - 1].provider if is_fallback else decision.fallback_from,
        )

        try:
            if is_fallback:
                logger.warning(
                    "Provider %s failed (%s) — falling back to %s/%s",
                    chain[i - 1].provider,
                    last_error.__class__.__name__,
                    candidate.provider,
                    candidate.model,
                )

            return await llm_client.complete(
                decision=current_decision,
                messages=messages,
                max_tokens=max_tokens,
                request_id=request_id,
                session_id=session_id,
            )

        except Exception as e:
            last_error = e
            logger.error(
                "Provider %s/%s failed: %s",
                candidate.provider,
                candidate.model,
                str(e),
            )
            continue

    # All candidates exhausted
    raise HTTPException(
        status_code=503,
        detail={
            "error": "all_providers_failed",
            "message": (
                f"All providers in the fallback chain failed for preference "
                f"'{preference.value}'. Last error: {str(last_error)}"
            ),
        },
    )