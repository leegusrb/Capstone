"""
services/student_llm.py
------------------------
Student LLM agent.

Role:
  - Ask the user questions while maintaining a "knows nothing" student persona.
  - Can only reference confirmed/partial nodes from the User KG (missing nodes are blocked from access and exposure).
  - Generates the next question using the Evaluator's feedback_summary and weak_areas.
  - Also generates the first question (ice_breaker) at session start.

Core design principles:
  - All concept lists inserted into prompts are dynamically extracted from the actual User KG
  - Missing nodes are never included in the prompt (blocked at architecture level)
  - Topic is taken directly from the document uploaded by the learner and the value entered at session start
"""

import json
import logging
from dataclasses import dataclass

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=settings.openai_api_key)


# ── Data classes ──────────────────────────────────────────

@dataclass
class StudentResponse:
    question: str
    intent: str  # ice_breaker | clarify_partial | probe_depth | request_example | check_relation


# ── Prompts ───────────────────────────────────────────────

STUDENT_SYSTEM_PROMPT = """\
[Role]
You are a student listening to a teacher explain a concept.
You have ZERO prior knowledge — you only know what the teacher has explicitly said in this conversation.

[Core Constraint]
- Your ONLY source of knowledge is what the teacher has said so far in this conversation.
- You do NOT have access to any textbooks, reference material, or external knowledge.
- Never infer, assume, or complete information that the teacher did not explicitly state.

[Conversation Phase]
Before asking, assess the current phase based on what the teacher has said so far:

Phase 1 — The teacher has introduced the topic but has NOT provided any explanation about the key concepts.
           → Ask the teacher to begin explaining the substance of the topic.

Phase 2 — The teacher has provided some explanation about the key concepts,
           but the explanation is incomplete, unclear, or missing critical details.
           → Ask about the most critical missing or unclear part.
           → "Most critical" = without this, understanding the explanation is impossible.

Phase 3 — The teacher has explained the key concepts clearly, but has NOT provided a concrete example or illustration.
           → Ask for a concrete example or illustration to better understand the topic.

[Question Rules]
1. Your question must target EXACTLY ONE concept or term — not a group, not a list.
   - If the teacher mentioned multiple items (e.g., A, B, C, D),
     pick the FIRST one and ask only about that.
   - NEVER combine multiple items into one question using "each", "all", "every".
   - BAD:  "What color are apples, strawberries, grapes, and oranges, respectively?"
   - GOOD: "What color is an apple?"
2. Ask ONLY ONE question per response. 1–2 sentences max.
3. Do NOT praise the explanation.
4. Respond in English.
5. For confirmed concepts, you may briefly acknowledge understanding (e.g., "I understand that part.").
6. For partial concepts, ask for more detail (e.g., "Could you explain that a bit more?").
7. Do NOT directly mention concepts that have not been explained yet.
8. Write in a friendly and natural tone.

When deciding WHAT to ask (Phase 2 priority order):
  1st — The most critical piece the teacher implied but never actually explained
  2nd — A cause-and-effect that was stated but not explained ("Why is that?")
  3rd — A concept mentioned but left incomplete

[Question Intent Types]
- ice_breaker     : First question at the start of a session
- clarify_partial : Request further explanation of a partial concept
- probe_depth     : Explore the mechanism or reasoning behind a confirmed concept
- request_example : Ask for a concrete example or real-world application
- check_relation  : Clarify the relationship between two concepts

You MUST respond ONLY in the following JSON format:
{
  "question": "Your question text here",
  "intent": "intent tag"
}
"""

_STUDENT_FIRST_TURN_TEMPLATE = """\
=== Learning Topic ===
{topic}

=== Situation ===
The session has just started.
You have not received any explanation from the teacher yet.
Generate the very first question asking the teacher to explain {topic} from the beginning.
Mention the topic name directly, and keep it an open-ended question at the level of "what is this" or "what is it about".
"""

_STUDENT_FOLLOWUP_TEMPLATE = """\
=== Learning Topic ===
{topic}

=== My Current Understanding (based only on what the teacher has explained) ===
Fully understood concepts    : {confirmed_nodes}
Partially understood concepts: {partial_nodes}
Understood relationships     : {confirmed_edges}
Incomplete relationships     : {partial_edges}

=== Evaluator Feedback (internal reference — do NOT mention this to the user) ===
Areas needing improvement    : {weak_areas}
Summary of this explanation  : {feedback_summary}

=== Recent Conversation This Session ===
{conversation_snippet}

=== Question Generation Guidelines ===
- If partial concepts exist, prioritize asking for further explanation of those.
- If weak_areas includes "specificity", ask for a concrete example.
- If weak_areas includes "logic", ask about the process or sequence of steps.
- If weak_areas includes "accuracy", ask to re-confirm the core definition or principle.
- If weak_areas includes "concept", ask a guiding question to surface the missing key concept.
- If all concepts are confirmed and none are partial, probe deeper into one confirmed concept.
- Do NOT repeat a question that is the same as or very similar to a previous one.
- Generate exactly ONE question.
"""


# ── Internal helpers ──────────────────────────────────────

def _format_edges(edges: list[dict]) -> str:
    if not edges:
        return "(none)"
    return ", ".join(
        f"{e.get('source', '')} -[{e.get('relation', '')}]-> {e.get('target', '')}"
        for e in edges
    )


def _format_conversation(history: list[dict], last_n: int = 6) -> str:
    """Include only the last N messages to save tokens."""
    recent = history[-last_n:] if len(history) > last_n else history
    if not recent:
        return "(no conversation yet)"
    lines = []
    for msg in recent:
        role = "Teacher (user)" if msg["role"] == "user" else "Me (student)"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def _parse_student_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception as e:
        logger.warning("Student JSON parsing failed, using full text as question: %s", e)
        return {"question": raw.strip(), "intent": "probe_depth"}


# ── Main function ─────────────────────────────────────────

def generate_student_question(
    topic: str,
    student_context: dict,
    conversation_history: list[dict],
    evaluator_feedback: str = "",
    weak_areas: list[str] | None = None,
    missing_nodes: list[str] | None = None,
    model: str = "gpt-4o-mini",
) -> StudentResponse:
    """
    Generate the next question from the Student LLM.

    Args:
        topic                : Learning topic string entered by the user at session start
        student_context      : Result of kg_service.get_student_context()
                               Contains only confirmed/partial nodes and edges — no missing nodes
        conversation_history : Full conversation history for this session
        evaluator_feedback   : Evaluator.feedback_summary (empty string = first turn)
        weak_areas           : Evaluator.weak_areas
        missing_nodes        : Result of get_missing_nodes() — for internal logging only, never inserted into prompt
        model                : OpenAI model name
    """
    weak_areas    = weak_areas    or []
    missing_nodes = missing_nodes or []

    is_first_turn = not conversation_history

    if is_first_turn:
        user_prompt = _STUDENT_FIRST_TURN_TEMPLATE.format(topic=topic)
    else:
        confirmed_nodes = student_context.get("confirmed_nodes", [])
        partial_nodes   = student_context.get("partial_nodes", [])
        confirmed_edges = student_context.get("confirmed_edges", [])
        partial_edges   = student_context.get("partial_edges", [])

        user_prompt = _STUDENT_FOLLOWUP_TEMPLATE.format(
            topic=topic,
            confirmed_nodes=", ".join(confirmed_nodes) if confirmed_nodes else "(none)",
            partial_nodes=", ".join(partial_nodes)     if partial_nodes   else "(none)",
            confirmed_edges=_format_edges(confirmed_edges),
            partial_edges=_format_edges(partial_edges),
            weak_areas=", ".join(weak_areas)           if weak_areas      else "(none)",
            feedback_summary=evaluator_feedback        if evaluator_feedback else "(none)",
            conversation_snippet=_format_conversation(conversation_history),
        )

    logger.info(
        "Student call — first turn: %s | confirmed %d | partial %d | missing %d (not exposed)",
        is_first_turn,
        len(student_context.get("confirmed_nodes", [])),
        len(student_context.get("partial_nodes", [])),
        len(missing_nodes),
    )

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": STUDENT_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.6,
        response_format={"type": "json_object"},
    )

    data = _parse_student_json(response.choices[0].message.content)

    result = StudentResponse(
        question=data.get("question", ""),
        intent=data.get("intent", "probe_depth"),
    )

    logger.info("Student question — intent: %s | %s", result.intent, result.question[:80])
    return result


def generate_session_closing_message(
    topic: str,
    termination_reason: str,
    session_summary: dict,
    model: str = "gpt-4o-mini",
) -> str:
    """
    Generate the student agent's closing message at session end.

    Args:
        topic               : Learning topic
        termination_reason  : "score" | "repetition" | "turn_limit" | "user"
        session_summary     : Return value of build_session_summary()
                              (contains actual values like final_coverage, missing_nodes, etc.)
        model               : OpenAI model name
    """
    coverage         = session_summary.get("final_coverage", {})
    missing          = session_summary.get("missing_nodes", [])
    coverage_percent = coverage.get("coverage_percent", 0)

    reason_comment_map = {
        "score":      "I feel like I understood a lot thanks to you!",
        "repetition": "Some parts still feel a bit unclear to me. It might help to review the material again.",
        "turn_limit": "It looks like it's time to wrap up today's session.",
        "user":       "Got it, let's stop here for today.",
    }
    reason_comment = reason_comment_map.get(termination_reason, "Ending the session.")

    missing_str = (
        f"'{', '.join(missing[:5])}'" + (" and more" if len(missing) > 5 else "")
        if missing else "none"
    )

    prompt = f"""\
Learning topic: {topic}
Session termination reason: {termination_reason} — {reason_comment}
KG coverage: {coverage_percent}% ({coverage.get('confirmed_count', 0)}/{coverage.get('total_count', 0)} concepts explained)
Concepts not yet explained: {missing_str}

As the student agent, write a natural and warm closing message in 2–4 sentences.
- If coverage is 70% or above, focus on praise. If below, focus on encouragement.
- If there are incomplete concepts, suggest covering them in the next session.
- Write naturally without fixed phrases.
"""

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are the student agent in a Feynman-technique learning service. Respond in a warm and encouraging tone.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()