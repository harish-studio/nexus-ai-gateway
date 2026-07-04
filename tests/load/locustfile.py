# tests/load/locustfile.py
"""
Locust load test for nexus-ai-gateway.

Run locally against the Docker stack:
    locust -f tests/load/locustfile.py --host http://localhost:8000

Recommended local settings (GTX 1650 constraint):
    Users: 5-10
    Spawn rate: 1/second
    Duration: 60-120 seconds

Three user classes reflect realistic traffic distribution:
    NovelQueryUser    60% — unique questions, zero cache hits
    MixedUser         30% — 70% repeated / 30% novel
    CacheWarmingUser  10% — fixed question pool, maximum cache hits

Auth: uses dedicated load-test API key (nexus-key-loadtest:loadtest_user)
so load test traffic is identifiable in the audit log by user_id.

Results to capture for SCALING.md and COST_MODEL.md:
    - p50/p95/p99 latency per endpoint
    - Cache hit rate (visible in gateway logs)
    - First bottleneck under load (GPU vs Redis vs Postgres)
    - RPS at which error rate exceeds 1%

Cloud Run load testing: deferred to shared deploy phase (post all-5-projects).
See SCALING.md for projected scaling behaviour.
"""

import random
import uuid

from locust import HttpUser, between, task


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

API_KEY = "nexus-key-loadtest"

HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
}

# Fixed question pool — used by CacheWarmingUser and MixedUser's repeat fraction
REPEATED_QUESTIONS = [
    "What is Python?",
    "Explain REST APIs in simple terms.",
    "What is the difference between SQL and NoSQL?",
    "How does HTTPS work?",
    "What is a microservice?",
]

# Novel question templates — uuid suffix ensures uniqueness per request
NOVEL_QUESTION_TEMPLATES = [
    "Explain the concept of {topic} in software architecture.",
    "What are the trade-offs between {topic} and alternatives?",
    "How would you design a system that handles {topic} at scale?",
    "What are the key considerations for {topic} in an enterprise context?",
    "Compare {topic} approaches for a high-throughput data pipeline.",
]

NOVEL_TOPICS = [
    "event sourcing", "CQRS", "saga pattern", "circuit breaker",
    "rate limiting", "semantic caching", "vector search",
    "RAG pipelines", "LLM orchestration", "agentic workflows",
    "EU AI Act compliance", "data residency", "PII redaction",
    "LLMOps", "model routing", "fallback chains",
]


def _novel_question() -> str:
    template = random.choice(NOVEL_QUESTION_TEMPLATES)
    topic = random.choice(NOVEL_TOPICS)
    # UUID suffix guarantees cache miss even if same template+topic recurs
    return f"{template.format(topic=topic)} [ref:{uuid.uuid4().hex[:8]}]"


def _chat_payload(content: str, preference: str = "auto") -> dict:
    return {
        "messages": [{"role": "user", "content": content}],
        "model_preference": preference,
        "max_tokens": 50,
        "stream": False,
        "user_id": "loadtest_user",
        "session_id": f"load-{uuid.uuid4().hex[:8]}",
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# User classes
# ---------------------------------------------------------------------------

class NovelQueryUser(HttpUser):
    """
    60% of traffic — unique questions every request.
    Exercises full pipeline: PII → classifier → cache MISS → LLM → audit.
    Latency here reflects worst-case (no cache benefit).
    """
    weight = 60
    wait_time = between(2, 5)

    @task(3)
    def chat_novel(self):
        self.client.post(
            "/chat",
            json=_chat_payload(_novel_question(), preference="auto"),
            headers=HEADERS,
            name="/chat [novel]",
        )

    @task(1)
    def chat_stream_novel(self):
        with self.client.post(
            "/chat/stream",
            json=_chat_payload(_novel_question(), preference="local"),
            headers=HEADERS,
            name="/chat/stream [novel]",
            stream=True,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Stream failed: {response.status_code}")


class MixedUser(HttpUser):
    """
    30% of traffic — 70% repeated questions, 30% novel.
    Realistic production pattern: some questions recur, most are unique.
    """
    weight = 30
    wait_time = between(1, 4)

    @task(7)
    def chat_repeated(self):
        question = random.choice(REPEATED_QUESTIONS)
        self.client.post(
            "/chat",
            json=_chat_payload(question, preference="auto"),
            headers=HEADERS,
            name="/chat [repeated]",
        )

    @task(3)
    def chat_novel(self):
        self.client.post(
            "/chat",
            json=_chat_payload(_novel_question(), preference="accurate"),
            headers=HEADERS,
            name="/chat [mixed-novel]",
        )

    @task(1)
    def chat_stream_repeated(self):
        question = random.choice(REPEATED_QUESTIONS)
        with self.client.post(
            "/chat/stream",
            json=_chat_payload(question, preference="local"),
            headers=HEADERS,
            name="/chat/stream [repeated]",
            stream=True,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Stream failed: {response.status_code}")


class CacheWarmingUser(HttpUser):
    """
    10% of traffic — rotates through 5 fixed questions.
    Maximises cache hit rate. Latency here reflects best-case
    (cache serves response without LLM call).
    """
    weight = 10
    wait_time = between(1, 3)

    @task(4)
    def chat_cached(self):
        question = random.choice(REPEATED_QUESTIONS)
        self.client.post(
            "/chat",
            json=_chat_payload(question, preference="local"),
            headers=HEADERS,
            name="/chat [cache-warming]",
        )

    @task(1)
    def chat_stream_cached(self):
        question = random.choice(REPEATED_QUESTIONS)
        with self.client.post(
            "/chat/stream",
            json=_chat_payload(question, preference="local"),
            headers=HEADERS,
            name="/chat/stream [cache-warming]",
            stream=True,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Stream failed: {response.status_code}")