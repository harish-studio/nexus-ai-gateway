# app/services/llm_client.py

import time, litellm
from app.schemas.provider import RoutingDecision
from app.schemas.request import ChatRequest
from app.schemas.response import ChatResponse
from app.services.cost_calculator import CostCalculator
from app.config.settings import settings

cost_calculator = CostCalculator()

# Tell LiteLLM where Ollama lives — it defaults to localhost:11434
# which is wrong inside Docker. Read from settings so it works in
# all environments (Docker, native, CI) without code changes.
OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL or "http://host.docker.internal:11434"


async def complete(
    decision: RoutingDecision,
    messages: list[dict],
    max_tokens: int,
    request_id: str,
    session_id: str,
) -> ChatResponse:
    t0 = time.monotonic()

    extra_params = {}
    if decision.provider == "ollama_chat":
        extra_params["api_base"] = OLLAMA_BASE_URL
        extra_params["extra_body"] = {"think": False}
        extra_params["options"] = {"think": False}  # belt-and-braces: Ollama native API

    response = await litellm.acompletion(
        model=f"ollama_chat/{decision.chosen_model}" if decision.provider == "ollama_chat" else f"{decision.provider}/{decision.chosen_model}",
        messages=messages,
        max_tokens=max_tokens,
        **extra_params,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    usage = getattr(response, "usage", None)
    if usage is None:
        raw_response = getattr(response, "raw_response", None)
        if isinstance(raw_response, dict):
            usage = raw_response.get("usage")

    prompt_tokens = 0
    completion_tokens = 0
    if usage is not None:
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
        else:
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)

    content = ""
    choices = getattr(response, "choices", None)
    if choices is None:
        raw_response = getattr(response, "raw_response", None)
        if isinstance(raw_response, dict):
            choices = raw_response.get("choices")

    if choices:
        first_choice = choices[0]
        if hasattr(first_choice, "message"):
            content = first_choice.message.content
        elif isinstance(first_choice, dict):
            content = first_choice.get("message", {}).get("content", "")
    else:
        content = getattr(response, "content", "")

    return ChatResponse(
        request_id=request_id,
        content=content,
        model_used=str(response.model),
        provider=decision.provider,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        cost_usd=cost_calculator.compute(
            decision.provider,
            decision.chosen_model,
            prompt_tokens,
            completion_tokens,
        ),
        latency_ms=latency_ms,
        cache_hit=False,
        session_id=session_id,
    )


async def stream(
    decision: RoutingDecision,
    request: "ChatRequest",
):
    extra_params = {}
    if decision.provider == "ollama_chat":
        extra_params["api_base"] = OLLAMA_BASE_URL
        extra_params["extra_body"] = {"think": False}
        extra_params["options"] = {"think": False}  # belt-and-braces: Ollama native API

    return await litellm.acompletion(
        model=f"ollama_chat/{decision.chosen_model}" if decision.provider == "ollama_chat" else f"{decision.provider}/{decision.chosen_model}",
        messages=[m.model_dump() for m in request.messages],
        max_tokens=request.max_tokens,
        stream=True,
        **extra_params,
    )