# app/services/risk_classifier.py
"""
EU AI Act risk classification for nexus-ai-gateway.

Classifies each request into one of four risk tiers defined by the
EU AI Act (Regulation 2024/1689):
  - UNACCEPTABLE: Article 5 prohibited practices → 403 reject
  - HIGH:         Annex III high-risk use cases → allow, flag in audit
  - LIMITED:      Article 50 transparency obligations → allow, log
  - MINIMAL:      Everything else → allow transparently

Classification method: intent + topic heuristic.
A request is classified at a tier only when it matches at least one
topic signal AND at least one intent signal from that tier's map.
Rationale: the Act classifies AI systems by purpose, not subject matter
alone - asking "what is a CV?" is not High Risk; making hiring decisions
is. Intent + topic captures this distinction more faithfully than
topic-only matching.

Reference: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689
"""

from __future__ import annotations
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Risk tier
# ---------------------------------------------------------------------------

class RiskTier:
    UNACCEPTABLE = "unacceptable"
    HIGH         = "high"
    LIMITED      = "limited"
    MINIMAL      = "minimal"


# ---------------------------------------------------------------------------
# Signal map - (topic_signals, intent_signals) per tier/domain
# ---------------------------------------------------------------------------

# Each entry is (frozenset of topic keywords, frozenset of intent keywords).
# A match requires at least one hit in EACH set (AND logic, not OR).

_UNACCEPTABLE_SIGNALS: list[tuple[frozenset, frozenset]] = [
    (
        frozenset(["social scoring", "citizen scoring", "social credit", "behaviour scoring"]),
        frozenset(["rank", "score", "rate", "evaluate", "classify"]),
    ),
    (
        frozenset(["subliminal", "subconscious", "manipulation", "nudge"]),
        frozenset(["influence", "manipulate", "target", "exploit"]),
    ),
    (
        frozenset(["biometric", "facial recognition", "real-time identification", "face scan"]),
        frozenset(["identify", "scan", "monitor", "surveil", "track"]),
    ),
    (
        frozenset(["vulnerability", "children", "minors", "elderly", "disability"]),
        frozenset(["exploit", "manipulate", "target", "deceive"]),
    ),
]

_HIGH_SIGNALS: list[tuple[frozenset, frozenset]] = [
    # Employment (Annex III §4)
    (
        frozenset(["cv", "resume", "candidate", "applicant", "hiring",
                   "recruitment", "interview", "job application"]),
        frozenset(["approve", "reject", "shortlist", "rank", "score",
                   "select", "assess", "screen"]),
    ),
    # Credit / finance (Annex III §5)
    (
        frozenset(["loan", "credit", "mortgage", "insurance",
                   "financial risk", "creditworthiness"]),
        frozenset(["approve", "reject", "assess", "score",
                   "determine", "decide", "evaluate"]),
    ),
    # Law enforcement (Annex III §6)
    (
        frozenset(["suspect", "criminal", "offender", "recidivism",
                   "threat", "crime", "perpetrator"]),
        frozenset(["identify", "predict", "assess", "flag",
                   "profile", "detect", "classify"]),
    ),
    # Medical (Annex III §5) - context guard: topic AND intent must co-occur
    (
        frozenset(["patient", "symptom", "medical", "clinical",
                   "diagnosis", "treatment", "disease", "condition"]),
        frozenset(["diagnose", "recommend", "prescribe",
                   "assess", "predict", "classify"]),
    ),
    # Education (Annex III §3)
    (
        frozenset(["student", "exam", "admission", "academic",
                   "grade", "assessment", "test score"]),
        frozenset(["assess", "evaluate", "score", "admit",
                   "reject", "rank", "predict"]),
    ),
    # Migration / border control (Annex III §7)
    (
        frozenset(["visa", "asylum", "refugee", "border",
                   "immigration", "nationality", "travel document"]),
        frozenset(["assess", "approve", "reject", "screen",
                   "identify", "verify", "classify"]),
    ),
    # Critical infrastructure (Annex III §2)
    (
        frozenset(["power grid", "water supply", "transport",
                   "traffic", "energy", "critical infrastructure"]),
        frozenset(["control", "manage", "operate", "access",
                   "disrupt", "override"]),
    ),
]

_LIMITED_SIGNALS: list[tuple[frozenset, frozenset]] = [
    # Chatbot / AI impersonation (Article 50 §1)
    (
        frozenset(["chatbot", "virtual assistant", "ai assistant",
                   "customer service bot", "automated agent"]),
        frozenset(["pretend", "act as", "roleplay", "simulate",
                   "impersonate", "pose as"]),
    ),
    # Emotion recognition (Article 50 §3)
    (
        frozenset(["emotion", "sentiment", "feeling", "mood",
                   "affect", "facial expression"]),
        frozenset(["detect", "recognise", "recognize", "analyse",
                   "analyze", "infer", "classify"]),
    ),
    # Deepfake / synthetic media (Article 50 §4)
    (
        frozenset(["deepfake", "synthetic media", "generated image",
                   "ai generated", "synthetic video", "fake video"]),
        frozenset(["create", "generate", "produce", "make",
                   "synthesise", "synthesize"]),
    ),
]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassificationResult:
    tier: str
    reason: str       # human-readable explanation for audit log
    matched_topic: str | None = None
    matched_intent: str | None = None


def _extract_text(messages: list[dict]) -> str:
    """Concatenate all message contents into a single lowercase string."""
    parts = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content.lower())
    return " ".join(parts)


def _matches(text: str, signal_groups: list[tuple[frozenset, frozenset]]) -> tuple[str, str] | None:
    """
    Returns (matched_topic, matched_intent) if the text matches any
    signal group, otherwise None.
    A match requires at least one keyword from the topic set AND at
    least one keyword from the intent set.
    """
    for topic_signals, intent_signals in signal_groups:
        matched_topic = next(
            (kw for kw in topic_signals if kw in text), None
        )
        if matched_topic is None:
            continue
        matched_intent = next(
            (kw for kw in intent_signals if kw in text), None
        )
        if matched_intent is not None:
            return matched_topic, matched_intent
    return None


def classify(messages: list[dict]) -> ClassificationResult:
    """
    Classifies a conversation into an EU AI Act risk tier.
    Checks tiers in descending severity order - first match wins.
    Returns MINIMAL if no signals match.
    """
    text = _extract_text(messages)

    # Unacceptable - Article 5 prohibited practices
    match = _matches(text, _UNACCEPTABLE_SIGNALS)
    if match:
        return ClassificationResult(
            tier=RiskTier.UNACCEPTABLE,
            reason=(
                f"Request matches Article 5 prohibited practice - "
                f"topic: '{match[0]}', intent: '{match[1]}'"
            ),
            matched_topic=match[0],
            matched_intent=match[1],
        )

    # High - Annex III use cases
    match = _matches(text, _HIGH_SIGNALS)
    if match:
        return ClassificationResult(
            tier=RiskTier.HIGH,
            reason=(
                f"Request matches Annex III high-risk use case - "
                f"topic: '{match[0]}', intent: '{match[1]}'"
            ),
            matched_topic=match[0],
            matched_intent=match[1],
        )

    # Limited - Article 50 transparency obligations
    match = _matches(text, _LIMITED_SIGNALS)
    if match:
        return ClassificationResult(
            tier=RiskTier.LIMITED,
            reason=(
                f"Request matches Article 50 limited-risk category - "
                f"topic: '{match[0]}', intent: '{match[1]}'"
            ),
            matched_topic=match[0],
            matched_intent=match[1],
        )

    # Minimal - no signals matched
    return ClassificationResult(
        tier=RiskTier.MINIMAL,
        reason="No EU AI Act risk signals detected",
    )