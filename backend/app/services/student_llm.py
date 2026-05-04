"""
services/student_llm.py
------------------------
Student LLM agent.

Role:
  - Ask the user questions while maintaining a "knows nothing" student persona.
  - Can only reference confirmed/partial nodes from the User KG.
  - Generates the next question using only the User KG and conversation history.
  - Also generates the first question (ice_breaker) at session start.

Core design principles:
  - All concept lists inserted into prompts are dynamically extracted from the actual User KG
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
===역할===
당신은 선생님의 설명을 듣는 학생입니다.
사전 지식이 전혀 없으며, 오직 이 대화에서 선생님이 명시적으로 말한 내용만 알고 있습니다.

===핵심 제약===
- 당신의 유일한 지식 출처는 지금까지 선생님이 말한 내용뿐입니다.
- 교재, 참고 자료, 외부 지식에는 접근할 수 없습니다.
- 선생님이 명시적으로 말하지 않은 내용은 절대로 추론하거나 가정하거나 채워 넣지 마세요.

===대화 단계===
질문하기 전에, 지금까지 선생님이 말한 내용을 바탕으로 현재 단계를 판단하세요:

Phase 1 — 선생님이 주제를 소개했지만, 핵심 개념에 대한 설명은 아직 없는 상태입니다.
           → 선생님에게 주제의 본질적인 내용을 설명해 달라고 요청하세요.

Phase 2 — 선생님이 핵심 개념에 대해 어느 정도 설명했지만,
           설명이 불완전하거나 불명확하거나 중요한 세부 사항이 빠져 있는 상태입니다.
           → 가장 핵심적으로 부족하거나 불명확한 부분에 대해 질문하세요.
           → "가장 핵심적"이란, 이것 없이는 설명 자체를 이해할 수 없는 내용을 의미합니다.

Phase 3 — 선생님이 핵심 개념을 명확하게 설명했지만, 구체적인 예시나 사례는 아직 없는 상태입니다.
           → 더 잘 이해할 수 있도록 구체적인 예시나 사례를 요청하세요.
     
===질문 규칙===
1. 질문은 반드시 정확히 하나의 개념이나 용어만 대상으로 해야 합니다. 여러 개를 묶어서 질문하지 마세요.
   - 선생님이 여러 항목(예: A, B, C, D)을 언급했다면, 첫 번째 항목만 골라서 질문하세요.
   - "각각", "모두", "전부" 등의 표현으로 여러 항목을 하나의 질문에 묶지 마세요.
   - 나쁜 예: "사과, 딸기, 포도, 오렌지는 각각 무슨 색인가요?"
   - 좋은 예: "사과는 무슨 색인가요?"
2. 응답당 질문은 반드시 하나만 하세요. 최대 1~2문장으로 제한합니다.
3. 설명을 칭찬하지 마세요.
4. 한국어로 답변하세요.
5. confirmed 개념에 대해서는 이해했다고 간략히 표현해도 됩니다. (예: "그 부분은 이해했어요.")
6. partial 개념에 대해서는 추가 설명을 요청하세요. (예: "그 부분을 좀 더 설명해 주실 수 있나요?")
7. 아직 설명되지 않은 개념을 직접 언급하지 마세요.
8. 친근하고 자연스러운 어조로 작성하세요.


===질문 의도 유형===
- ice_breaker     : 세션 시작 시 첫 번째 질문
- clarify_partial : partial 개념에 대해 추가 설명 요청
- probe_depth     : confirmed 개념의 원리나 이유 탐구
- request_example : 구체적인 예시나 실제 적용 사례 요청
- check_relation  : 두 개념 간의 관계 명확화

반드시 아래 JSON 형식으로만 응답하세요:
{
  "question": "질문 내용",
  "intent": "의도 태그"
}
"""

_STUDENT_FIRST_TURN_TEMPLATE = """\
=== 학습 주제 ===
{topic}

=== 상황 ===
세션이 방금 시작되었습니다.
아직 선생님으로부터 아무런 설명도 듣지 못했습니다.
선생님에게 {topic}에 대해 처음부터 설명해 달라고 요청하는 첫 번째 질문을 생성하세요.
주제 이름을 직접 언급하고, "오늘은 어떤 내용에 대해 배우나요?" 수준의 열린 질문으로 작성하세요.
"""

_STUDENT_FOLLOWUP_TEMPLATE = """\
=== 학습 주제 ===
{topic}

=== 나의 현재 이해 상태 (선생님이 설명한 내용만을 기반으로) ===
완전히 이해한 개념 (confirmed): {confirmed_nodes}
부분적으로 이해한 개념 (partial): {partial_nodes}
이해한 개념 간의 관계         : {confirmed_edges}
불완전하게 이해한 관계        : {partial_edges}

=== 이번 세션의 최근 대화 ===
{conversation_snippet}

=== 질문 생성 지침 ===
- partial 개념이 있다면 해당 개념에 대한 추가 설명을 우선 요청하세요.
- partial 개념이 없다면 아래 순서로 질문하세요:
  1순위 — 선생님이 암시했지만 실제로 설명하지 않은 핵심 내용
  2순위 — 언급은 했지만 이유를 설명하지 않은 인과관계
  3순위 — confirmed 개념 중 하나를 더 깊이 탐구
- 이전에 했던 질문과 동일하거나 유사한 질문은 반복하지 마세요.
- 질문은 정확히 하나만 생성하세요.
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
        role = "선생님 (사용자)" if msg["role"] == "user" else "나 (학생)"
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
    model: str = "gpt-4o-mini",
) -> StudentResponse:
    """
    Generate the next question from the Student LLM.

    Args:
        topic                : Learning topic string entered by the user at session start
        student_context      : Result of kg_service.get_student_context()
                               Contains only confirmed/partial nodes and edges
        conversation_history : Full conversation history for this session
        model                : OpenAI model name
    """
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
            conversation_snippet=_format_conversation(conversation_history),
        )

    logger.info(
        "Student call — first turn: %s | confirmed %d | partial %d",
        is_first_turn,
        len(student_context.get("confirmed_nodes", [])),
        len(student_context.get("partial_nodes", [])),
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
                              (contains actual values like coverage, missing_nodes, etc.)
        model               : OpenAI model name
    """
    coverage         = session_summary.get("coverage", {})
    missing          = session_summary.get("missing_nodes", [])
    coverage_percent = coverage.get("coverage_percent", 0)
    weak_areas       = session_summary.get("weak_areas", [])
    feedback_summary = session_summary.get("feedback_summary", "")

    reason_comment_map = {
        "score":      "선생님 덕분에 많이 이해한 것 같아요!",
        "repetition": "아직 일부 내용이 잘 이해되지 않아요. 자료를 다시 한번 복습해보는 게 좋을 것 같아요.",
        "turn_limit": "오늘 세션을 마무리할 시간이 된 것 같네요.",
        "user":       "알겠어요, 오늘은 여기서 마칠게요.",
    }
    reason_comment = reason_comment_map.get(termination_reason, "세션을 종료합니다.")

    missing_str = (
        f"'{', '.join(missing[:5])}'" + (" 외 다수" if len(missing) > 5 else "")
        if missing else "없음"
    )

    label_map = {
        "concept": "핵심 개념 포함도",
        "accuracy": "설명 정확도",
        "logic": "논리적 흐름",
        "specificity": "구체성·예시",
    }
    weak_str = ", ".join(label_map.get(w, w) for w in weak_areas) if weak_areas else "없음"

    prompt = f"""\
학습 주제: {topic}
세션 종료 이유: {termination_reason} — {reason_comment}
KG 커버리지: {coverage_percent}% ({coverage.get('confirmed_count', 0)}/{coverage.get('total_count', 0)}개 개념 설명 완료)
아직 설명되지 않은 개념: {missing_str}
보완이 필요한 영역: {weak_str}
세션 피드백: {feedback_summary}

학생 에이전트로서 자연스럽고 따뜻한 마무리 인사를 3~5문장으로 작성하세요.
- 커버리지가 70% 이상이면 칭찬 위주로, 미만이면 격려 위주로 작성하세요.
- 보완이 필요한 영역이 있다면 구체적으로 언급하세요.
- 세션 피드백 내용을 자연스럽게 녹여내세요.
- 설명되지 않은 개념이 있다면 다음 세션에서 이어서 다뤄보자고 제안하세요.
- 정해진 형식 없이 자연스럽게 작성하세요.
"""

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "당신은 파인만 학습법 서비스의 학생 에이전트입니다.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()