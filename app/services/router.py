# app/services/router.py

from app.providers import get_provider
from app.schemas.provider import RoutingDecision
from app.schemas.request import ChatRequest, ModelPreference
from app.services.complexity import TRIVIAL_WORD_LIMIT, is_trivial

# Explicit target for ACCURATE→cheap downgrade — not provider.default_model,
# since the whole point is to reach the cheap tier specifically.
OPENAI_CHEAP_MODEL = "gpt-5.4-nano"


async def decide(request: ChatRequest) -> RoutingDecision:
    """
    Routes requests to the appropriate provider and model based on
    model_preference, with one complexity-based override:
      - ACCURATE + trivial prompt → downgraded to OpenAI cheap tier
        to avoid overpaying for simple questions.
    LOCAL is a hard constraint and is never overridden.
    Complexity scoring and PII-triggered overrides: Day 3-4.
    """

    if request.model_preference == ModelPreference.LOCAL:
        provider = get_provider("ollama")
        return RoutingDecision(
            provider=provider.name,
            chosen_model=provider.default_model,
            reason="Client requested LOCAL — routed to Ollama",
        )

    if request.model_preference == ModelPreference.FAST:
        provider = get_provider("openai")
        return RoutingDecision(
            provider=provider.name,
            chosen_model=provider.default_model,  # gpt-5.4
            reason="Client requested FAST — routed to cheapest capable model",
        )

    if request.model_preference == ModelPreference.ACCURATE:
        messages_as_dicts = [m.model_dump() for m in request.messages]

        if is_trivial(messages_as_dicts):
            provider = get_provider("openai")
            return RoutingDecision(
                provider=provider.name,
                chosen_model=OPENAI_CHEAP_MODEL,
                reason=(
                    f"Client requested ACCURATE but prompt was trivial "
                    f"(single message, under {TRIVIAL_WORD_LIMIT} words, "
                    f"no code/reasoning markers) — downgraded to "
                    f"{OPENAI_CHEAP_MODEL} to avoid overpaying"
                ),
                fallback_from="anthropic",
            )

        provider = get_provider("anthropic")
        return RoutingDecision(
            provider=provider.name,
            chosen_model=provider.default_model,  # claude-sonnet-4-6
            reason="Client requested ACCURATE — routed to highest-capability model",
        )

    # AUTO (and structural default for any future enum value):
    # lowest-priority-number provider's default model
    provider = sorted(
        [get_provider(n) for n in ("anthropic", "openai", "ollama")],
        key=lambda p: p.priority,
    )[0]
    return RoutingDecision(
        provider=provider.name,
        chosen_model=provider.default_model,
        reason=f"AUTO preference — selected {provider.name} by priority order",
    )