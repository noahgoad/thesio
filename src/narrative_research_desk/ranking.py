"""Evidence-labelled research prioritization; not a return or trade forecast."""
from __future__ import annotations
from typing import Any

def research_score(quality: float, relevance: float, recency: float, conflict: float) -> float:
    values = (quality, relevance, recency, conflict)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1 for value in values):
        raise ValueError("SCORE_RANGE")
    return 0.4 * quality + 0.3 * relevance + 0.3 * recency - 0.3 * conflict

def rank_research(components: dict[str, Any]) -> dict[str, Any]:
    score = research_score(components.get("quality"), components.get("relevance"), components.get("recency"), components.get("conflict"))
    return {"classification": "RESEARCH_PRIORITY", "score": score, "components": {key: components[key] for key in ("quality", "relevance", "recency", "conflict")}, "limitation": "Research priority only; not an expected-return or execution signal."}
