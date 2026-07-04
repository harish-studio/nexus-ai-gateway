# app/routers/chat.py

import os
from typing import AsyncGenerator
from uuid import uuid4

import litellm
import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request, Security
from fastapi import Response as FastAPIResponse
from fastapi.responses import StreamingResponse

from app.schemas.provider import RoutingDecision
from app.schemas.request import ChatRequest
from app.schemas.response import ChatResponse
from app.services import llm_client
from app.services.audit_service import build_audit_record, write_audit_record
from app.services.auth import validate_api_key
from app.services.fallback import execute as fallback_execute
from app.services.limiter import limiter
from app.services.pii_detector import (
    RESPONSE_MONITORED_ENTITIES,
    check_messages,
    detect_pii,
)
from app.services.risk_classifier import RiskTier, classify
from app.services.router import decide
from app.services.semantic_cache import get_cached_response, store_response

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("10/minute;50/hour")
async def chat(
    request: Request,
    chat_request: ChatRequest,
    fastapi_response: FastAPIResponse,
    user_label: str = Security(validate_api_key),
) -> ChatResponse:
    messages_as_dicts = [m.model_dump() for m in chat_request.messages]

    # Gate 1 — PII check on request
    pii_in_request = check_messages(messages_as_dicts)
    if pii_in_request:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "pii_detected_in_request",
                "entities": sorted(pii_in_request),
                "message": (
                    "Request contains personal data. "
                    "Remove PII before submitting to this gateway."
                ),
            },
        )

    # Gate 2 — EU AI Act risk classification
    classification = classify(messages_as_dicts)

    if classification.tier == RiskTier.UNACCEPTABLE:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "request_prohibited",
                "risk_tier": classification.tier,
                "reason": classification.reason,
                "message": (
                    "This request has been classified as an EU AI Act "
                    "Article 5 prohibited practice and cannot be processed."
                ),
            },
        )

    # Gate 3 — Semantic cache lookup
    redis_client = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0")
    )

    cached = None
    if classification.tier != "high":
        cached = await get_cached_response(redis_client, messages_as_dicts)

    if cached is not None:
        cached_response = ChatResponse(**cached)
        cached_response.cache_hit = True
        cached_response.request_id = str(uuid4())

        cache_decision = RoutingDecision(
            provider     = cached_response.provider,
            chosen_model = cached_response.model_used,
            reason       = "Cache hit — response served from semantic cache",
        )
        cache_audit = build_audit_record(
            request_id      = cached_response.request_id,
            user_id         = user_label,  # from API key, not request body
            session_id      = chat_request.session_id,
            requested_model = chat_request.model_preference.value,
            decision        = cache_decision,
            classification  = classification,
            pii_entities    = pii_in_request,
            response        = cached_response,
        )
        await write_audit_record(cache_audit)
        return cached_response

    # Gate 4 — Route and execute with fallback chain
    decision = await decide(chat_request)

    response = await fallback_execute(
        decision        = decision,
        preference      = chat_request.model_preference,
        messages        = messages_as_dicts,
        max_tokens      = chat_request.max_tokens,
        request_id      = str(uuid4()),
        session_id      = chat_request.session_id,
    )

    # Gate 5 — PII check on response (egress)
    pii_in_response = detect_pii(
        response.content,
        entities=RESPONSE_MONITORED_ENTITIES,
    )
    if pii_in_response:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "pii_detected_in_response",
                "entities": sorted(pii_in_response),
                "message": (
                    "The model response contained personal data and was blocked "
                    "at egress. Tokens were consumed — see audit log."
                ),
            },
        )

    # Gate 6 — Store in cache (skips High Risk internally)
    await store_response(
        redis_client,
        messages_as_dicts,
        response.model_dump(),
        classification.tier,
    )

    # Gate 7 — Article 13 transparency header for High Risk
    if classification.tier == RiskTier.HIGH:
        fastapi_response.headers["X-Risk-Tier"] = "high"
        fastapi_response.headers["X-Risk-Reason"] = classification.reason

    # Write audit record synchronously before returning
    audit_record = build_audit_record(
        request_id      = response.request_id,
        user_id         = user_label,  # from API key, not request body
        session_id      = chat_request.session_id,
        requested_model = chat_request.model_preference.value,
        decision        = decision,
        classification  = classification,
        pii_entities    = pii_in_request,
        response        = response,
    )
    await write_audit_record(audit_record)

    return response


@router.post("/chat/stream")
@limiter.limit("10/minute;50/hour")
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    user_label: str = Security(validate_api_key),
) -> StreamingResponse:
    messages_as_dicts = [m.model_dump() for m in chat_request.messages]

    # Gate 1 — PII check on request
    pii_in_request = check_messages(messages_as_dicts)
    if pii_in_request:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "pii_detected_in_request",
                "entities": sorted(pii_in_request),
                "message": (
                    "Request contains personal data. "
                    "Remove PII before submitting to this gateway."
                ),
            },
        )

    # Gate 2 — EU AI Act risk classification
    classification = classify(messages_as_dicts)
    if classification.tier == RiskTier.UNACCEPTABLE:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "request_prohibited",
                "risk_tier": classification.tier,
                "reason": classification.reason,
                "message": (
                    "This request has been classified as an EU AI Act "
                    "Article 5 prohibited practice and cannot be processed."
                ),
            },
        )

    decision = await decide(chat_request)

    extra_params = {}
    if decision.provider == "ollama":
        extra_params["api_base"] = llm_client.OLLAMA_BASE_URL
        extra_params["extra_body"] = {"think": False}

    async def event_generator() -> AsyncGenerator[str, None]:
        response_stream = await litellm.acompletion(
            model      = f"{decision.provider}/{decision.chosen_model}",
            messages   = messages_as_dicts,
            max_tokens = chat_request.max_tokens,
            stream     = True,
            **extra_params,
        )

        if isinstance(response_stream, litellm.CustomStreamWrapper):
            async for chunk in response_stream:
                delta = chunk.choices[0].delta.content
                yield delta or ""
        else:
            content = response_stream.choices[0].message.content
            yield content or ""

    return StreamingResponse(event_generator(), media_type="text/event-stream")