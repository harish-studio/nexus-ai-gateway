# app/services/complexity.py
"""
Heuristic prompt-complexity check used to decide whether an ACCURATE
request can be safely downgraded to a cheaper model. Deliberately
keyword/length-based rather than model-based — adding an LLM call here
to score complexity would defeat the purpose of a cost-protection feature.
"""

import re

TRIVIAL_WORD_LIMIT = 20

_COMPLEXITY_KEYWORDS = (
    "first", "then", "finally", "step",
    "explain why", "compare", "analyze", "analyse",
    "summarize", "summarise", "design", "architect",
    "debug", "optimize", "optimise",
)

_CODE_BLOCK_PATTERN = re.compile(r"```|^( {4}|\t)", re.MULTILINE)


def is_trivial(messages: list[dict]) -> bool:
    """
    A request is considered trivial — and therefore safe to downgrade
    from ACCURATE to a cheaper model — only if ALL of the following hold:
      - it's a single message (no multi-turn context)
      - under TRIVIAL_WORD_LIMIT words
      - no code block markers
      - no multi-step / reasoning keywords
    """
    if len(messages) != 1:
        return False

    content = messages[0].get("content", "")
    if not content:
        return False

    if len(content.split()) > TRIVIAL_WORD_LIMIT:
        return False

    if _CODE_BLOCK_PATTERN.search(content):
        return False

    lowered = content.lower()
    if any(keyword in lowered for keyword in _COMPLEXITY_KEYWORDS):
        return False

    return True