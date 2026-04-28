"""
services/evaluator_llm.py
--------------------------
Evaluator LLM agent.

Role:
  - Score the user's explanation against RAG-based learning material using a 4-category rubric
  - Update the User KG (confirmed / partial / missing / misconception judgments)
  - Determine session termination (total score >= 10, repetition limit, or turn limit exceeded)
  - Generate hints for the next Student LLM question

Core design principles:
  - Reference KG / User KG are loaded directly from DB as-is
  - Node/edge lists inserted into prompts are dynamically extracted from the actual KG
  - No hardcoded example strings
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
from openai import OpenAI

from app.config import settings
from app.services.kg_service import (
    NodeStatus,
    get_missing_nodes,
    get_nodes_by_status,
)

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=settings.openai_api_key)

# ── Session termination thresholds ────────────────────────
SCORE_THRESHOLD      = 10
MAX_TURNS            = 10
REPETITION_WINDOW    = 3
REPETITION_MAX_SCORE = 2
SCORE_CATEGORIES     = ["concept", "accuracy", "logic", "specificity"]


# ── Data classes ──────────────────────────────────────────

@dataclass
class RubricScores:
    concept:     int = 0
    accuracy:    int = 0
    logic:       int = 0
    specificity: int = 0

    @property
    def total(self) -> int:
        return self.concept + self.accuracy + self.logic + self.specificity

    def to_dict(self) -> dict:
        return {
            "concept":     self.concept,
            "accuracy":    self.accuracy,
            "logic":       self.logic,
            "specificity": self.specificity,
        }


@dataclass
class EvaluatorResult:
    scores:             RubricScores
    total:              int
    is_sufficient:      bool            # True → session ends
    termination_reason: Optional[str]   # "score" | "repetition" | "turn_limit" | None
    updated_user_kg:    dict            # input for kg_service.update_user_kg_from_evaluator()
    misconceptions:     list[dict] = field(default_factory=list)
    weak_areas:         list[str]  = field(default_factory=list)
    feedback_summary:   str        = ""


# ── Prompts ───────────────────────────────────────────────

_EVALUATOR_SYSTEM_PROMPT = """\
You are the Evaluator LLM in a Feynman-technique-based learning service.

Role:
1. Evaluate the learner's explanation against the learning material (RAG chunks) and the Reference KG.
2. Score 4 rubric categories.
3. Extract concepts and relationships from the user's explanation to generate User KG update data.
4. Record any misconceptions found.

Rubric scoring criteria (0–3 per category):
- concept     : 0=almost no key concepts, 1=only some included, 2=most included, 3=all included without omission
- accuracy    : 0=critical errors present, 1=many ambiguous parts, 2=generally accurate but lacking detail, 3=both core and detail are accurate
- logic       : 0=just a list of sentences, 1=partial connections only, 2=flow exists but some leaps, 3=cause-process-result connected naturally
- specificity : 0=abstract expressions only, 1=slight concreteness, 2=concrete expressions included, 3=examples and application scenarios provided

User KG node status definitions:
- confirmed : The user explained this concept accurately and completely.
- partial   : The concept was mentioned but the explanation is incomplete, vague, or the relationship is unclear.
- missing   : Not yet explained. Do NOT change this status unless the concept was explicitly addressed in this explanation.

Critical rules for updating the User KG:
- Include in updated_user_kg ONLY nodes and edges that were explicitly mentioned in this explanation.
- If two concepts were mentioned separately but their relationship was NOT explained,
  the edge between them must remain or be set to "partial" — do NOT mark it as "confirmed".
- If the user incorrectly described a concept not in the Reference KG, record it in misconceptions.
- Return ONLY pure JSON. No markdown, no explanation text.
"""

# Node/edge lists are dynamically extracted from the actual KG at runtime and inserted here.
_EVALUATOR_USER_TEMPLATE = """\
=== Learning Material (RAG Search Results) ===
{rag_context}

=== Reference KG (evaluation standard — actual concept structure extracted from the document) ===
Node list : {reference_nodes}
Edge list : {reference_edges}

=== Current User KG State ===
Confirmed nodes : {confirmed_nodes}
Partial nodes   : {partial_nodes}
Missing nodes   : {missing_nodes}

=== User's Explanation ===
{user_explanation}

=== Output Format (return pure JSON only) ===
{{
  "scores": {{
    "concept": 0~3,
    "accuracy": 0~3,
    "logic": 0~3,
    "specificity": 0~3
  }},
  "total": 0~12,
  "updated_user_kg": {{
    "nodes": [
      {{"id": "<node from Reference KG that was mentioned in this explanation>", "status": "confirmed|partial|missing"}}
    ],
    "edges": [
      {{"source": "<node>", "relation": "<verb phrase>", "target": "<node>", "status": "confirmed|partial|missing"}}
    ]
  }},
  "misconceptions": [
    {{"content": "<user's incorrect statement>", "correction": "<correct explanation>"}}
  ],
  "weak_areas": ["categories scoring 2 or below: concept|accuracy|logic|specificity"],
  "feedback_summary": "A 2–3 sentence summary for the Student LLM to reference when generating the next question."
}}
"""


# ── Internal helpers ──────────────────────────────────────

def _build_rag_context(rag_chunks: list[str]) -> str:
    if not rag_chunks:
        return "(no learning material retrieved)"
    return "\n\n".join(f"[Chunk {i+1}]\n{chunk}" for i, chunk in enumerate(rag_chunks))


def _kg_to_prompt_strings(kg: nx.DiGraph) -> tuple[str, str]:
    """
    Extract nodes/edges from the actual KG graph and convert to strings for prompt insertion.
    Reflects only KG content generated from uploaded documents — no hardcoded examples.
    """
    nodes = [
        f"{node_id}(status={attrs.get('status', '?')})"
        for node_id, attrs in kg.nodes(data=True)
        if node_id != "__misconceptions__"
    ]
    edges = [
        f"{src} -[{attrs.get('relation', 'related')}]-> {tgt}"
        for src, tgt, attrs in kg.edges(data=True)
    ]
    return (
        ", ".join(nodes) if nodes else "(no nodes)",
        ", ".join(edges) if edges else "(no edges)",
    )


def _check_repetition_limit(
    session_history: list[dict],
    window: int,
    max_score: int,
) -> bool:
    """Returns True if all category scores are <= max_score for the last `window` turns."""
    if len(session_history) < window:
        return False
    recent = session_history[-window:]
    for category in SCORE_CATEGORIES:
        if any(turn.get(category, 3) > max_score for turn in recent):
            return False
    return True


def _parse_llm_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Evaluator JSON parsing failed: %s\nRaw output: %s", e, raw)
        raise ValueError(f"Evaluator LLM did not return valid JSON: {e}") from e


# ── Main function ─────────────────────────────────────────

def evaluate_explanation(
    user_explanation: str,
    user_kg: nx.DiGraph,
    reference_kg: nx.DiGraph,
    rag_chunks: list[str],
    session_history: list[dict],
    turn_count: int,
    model: str = "gpt-4o-mini",
) -> EvaluatorResult:
    """
    Evaluate the user's explanation and return an EvaluatorResult.

    Args:
        user_explanation : The user's explanation text for this turn
        user_kg          : Current User KG loaded from DB (nx.DiGraph)
        reference_kg     : Reference KG loaded from DB (nx.DiGraph) — based on uploaded document
        rag_chunks       : Actual chunk texts retrieved via similarity search for this explanation
        session_history  : List of scores dicts from previous turns
        turn_count       : Current turn number (1-indexed)
        model            : OpenAI model name
    """
    # Dynamically extract nodes/edges from the actual KG
    ref_nodes_str, ref_edges_str = _kg_to_prompt_strings(reference_kg)

    confirmed_nodes = get_nodes_by_status(user_kg, NodeStatus.CONFIRMED)
    partial_nodes   = get_nodes_by_status(user_kg, NodeStatus.PARTIAL)
    missing_nodes   = get_missing_nodes(user_kg)

    user_prompt = _EVALUATOR_USER_TEMPLATE.format(
        rag_context=_build_rag_context(rag_chunks),
        reference_nodes=ref_nodes_str,
        reference_edges=ref_edges_str,
        confirmed_nodes=", ".join(confirmed_nodes) if confirmed_nodes else "(none)",
        partial_nodes=", ".join(partial_nodes)     if partial_nodes   else "(none)",
        missing_nodes=", ".join(missing_nodes)     if missing_nodes   else "(none)",
        user_explanation=user_explanation,
    )

    logger.info(
        "Evaluator call — turn %d | ref nodes %d | confirmed %d | partial %d | missing %d | explanation %d chars",
        turn_count,
        reference_kg.number_of_nodes(),
        len(confirmed_nodes),
        len(partial_nodes),
        len(missing_nodes),
        len(user_explanation),
    )

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _EVALUATOR_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    data = _parse_llm_json(response.choices[0].message.content)

    scores_dict = data.get("scores", {})
    scores = RubricScores(
        concept=int(scores_dict.get("concept", 0)),
        accuracy=int(scores_dict.get("accuracy", 0)),
        logic=int(scores_dict.get("logic", 0)),
        specificity=int(scores_dict.get("specificity", 0)),
    )

    # ── Session termination check ──
    is_sufficient      = scores.total >= SCORE_THRESHOLD
    termination_reason = "score" if is_sufficient else None

    if not is_sufficient:
        history_with_current = session_history + [scores.to_dict()]
        if _check_repetition_limit(history_with_current, REPETITION_WINDOW, REPETITION_MAX_SCORE):
            is_sufficient      = True
            termination_reason = "repetition"

    if not is_sufficient and turn_count >= MAX_TURNS:
        is_sufficient      = True
        termination_reason = "turn_limit"

    result = EvaluatorResult(
        scores=scores,
        total=scores.total,
        is_sufficient=is_sufficient,
        termination_reason=termination_reason,
        updated_user_kg=data.get("updated_user_kg", {"nodes": [], "edges": []}),
        misconceptions=data.get("misconceptions", []),
        weak_areas=data.get("weak_areas", []),
        feedback_summary=data.get("feedback_summary", ""),
    )

    logger.info(
        "Evaluator result — %s | total %d | terminate %s (%s)",
        scores.to_dict(), scores.total, is_sufficient, termination_reason,
    )
    return result


def build_session_summary(
    session_history: list[dict],
    user_kg: nx.DiGraph,
    reference_kg: nx.DiGraph,
    termination_reason: str,
) -> dict:
    """Generate a summary dict to send to the frontend at session end."""
    from app.services.kg_service import get_kg_coverage

    score_trend = [
        {
            "turn":  i + 1,
            "total": sum(t.get(c, 0) for c in SCORE_CATEGORIES),
            **{c: t.get(c, 0) for c in SCORE_CATEGORIES},
        }
        for i, t in enumerate(session_history)
    ]

    avg_scores = (
        {
            cat: round(sum(t.get(cat, 0) for t in session_history) / len(session_history), 2)
            for cat in SCORE_CATEGORIES
        }
        if session_history else {}
    )

    return {
        "termination_reason": termination_reason,
        "score_trend":        score_trend,
        "final_coverage":     get_kg_coverage(user_kg, reference_kg),
        "missing_nodes":      get_missing_nodes(user_kg),
        "avg_scores":         avg_scores,
    }