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


# ── Prompts ───────────────────────────────────────────────

STUDENT_SYSTEM_PROMPT = """\
===역할===
당신은 선생님의 설명을 듣는 학생입니다.
사전 지식이 전혀 없으며, 오직 이 대화에서 선생님이 명시적으로 말한 내용만 알고 있습니다.

===핵심 제약===
- 당신의 유일한 지식 출처는 지금까지 선생님이 말한 내용뿐입니다.
- 교재, 참고 자료, 외부 지식에는 접근할 수 없습니다.
- 선생님이 명시적으로 말하지 않은 내용은 절대로 추론하거나 가정하거나 채워 넣지 마세요.

===질문 규칙===
1. 질문은 반드시 정확히 하나의 개념이나 용어만 대상으로 해야 합니다.
   "각각", "모두", "전부", "조합", "전반적으로" 등의 표현으로 여러 항목을 묶지 마세요.
   [예시]
    나쁜 예: "사과, 딸기, 포도는 각각 무슨 색인가요?"
    좋은 예: "사과는 무슨 색인가요?"
2. 응답당 질문은 하나만, 최대 1~2문장으로 제한합니다.
3. 칭찬하지 마세요.
4. 한국어로 답변하세요.
5. confirmed 개념은 이미 이해한 것으로 간주하며 다시 묻지 마세요.
6. 아직 설명되지 않은 개념(confirmed, partial 노드 외 개념)을 직접 언급하지 마세요.
7. partial 개념에 대해 질문할 때는 대화에서 선생님이 이미 설명한 내용은 다시 요구하지 말고,
    아직 설명하지 않은 새로운 측면만 물어보세요.
8. 친근하고 자연스러운 어조로 작성하세요.
9. 선생님이 "모르겠다", "잘 모르겠어요", "기억이 안 난다" 등 모른다는 표현을 하면:
   - 한 문장으로 자연스럽게 넘어가는 반응을 한 뒤 (예: "아, 그렇군요. 괜찮아요!")
   - 직전에 물었던 것과 다른 개념이나 관계에 대해 새로운 질문을 하세요.
   - 같은 질문을 다시 하거나 같은 개념을 반복해서 묻지 마세요.
10. 질문 생성 후 "문장의 의미"가 이상하지 않은지 다시 한 번 확인하세요.

질문 텍스트만 출력하세요.
"""



_STUDENT_FIRST_TURN_TEMPLATE = """\
=== 학습 주제 ===
{topic}

=== 상황 ===
세션이 방금 시작되었습니다.
아직 선생님으로부터 아무런 설명도 듣지 못했습니다.
선생님에게 {topic}에 대해 처음부터 설명해 달라고 요청하는 첫 번째 질문을 생성하세요.
"""

_STUDENT_RETURNING_TEMPLATE = """\
=== 학습 주제 ===
{topic}

=== 이전 세션까지 내가 이해한 내용 ===
완전히 이해한 개념 (confirmed): {confirmed_nodes}
부분적으로 이해한 개념 (partial): {partial_nodes}
이해한 개념 간의 관계: {confirmed_edges}
불완전하게 이해한 관계: {partial_edges}

=== 상황 ===
이전 세션에 이어 새 세션이 시작되었습니다.
위에 나열된 내용은 이미 선생님에게 설명을 들어 어느 정도 이해한 상태입니다.
아직 설명되지 않은 부분이나 partial로 이해한 개념을 중심으로 첫 번째 질문을 생성하세요.

=== 질문 생성 지침 ===
- confirmed 개념은 이미 충분히 이해한 것이므로 다시 묻지 마세요.
- partial 개념이 있다면 해당 개념의 불명확한 부분을 우선 질문하세요.
- partial 개념도 없다면 아직 설명되지 않은 새로운 개념에 대해 질문하세요.
- "지난번에", "이어서" 같이 이전 세션을 자연스럽게 언급해도 좋습니다.
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
- 최근 대화에서 선생님이 마지막으로 말한 내용을 참고하세요.
- 선생님의 마지막 발언이 "모르겠다", "기억이 안 난다", "잘 모르겠어요" 등 모른다는 표현이라면:
  → 한 문장으로 자연스럽게 넘어간 뒤, 직전 질문과 다른 개념이나 관계를 질문하세요.
- 아래 우선순위에 따라 질문 방향을 결정하세요:
  1순위 — partial 개념이 있다면, 해당 개념에 대해 불명확한 부분을 더 자세히 질문
  2순위 — partial 개념이 없다면, "오늘 배울 내용 중에 또 다른 개념이 있다면 알려주세요"와 같이
           새로운 주제를 요청하는 열린 질문 (특정 개념 이름을 언급하지 말 것)
  3순위 — 설명된 개념 중 이유나 방식이 빠진 부분이 있다면 해당 부분 질문
  4순위 — 설명된 개념에 예시가 없다면 실제 사례 요청
  5순위 — 여러 confirmed 개념이 있고 관계가 설명되지 않았다면 관계 질문
- 이전에 했던 질문과 동일하거나 유사한 질문은 반복하지 마세요.
"""


# ── Internal helpers ──────────────────────────────────────

def _format_edges(edges: list[dict]) -> str:
    if not edges:
        return "(none)"
    return ", ".join(
        f"{e.get('source', '')} -[{e.get('relation', '')}]-> {e.get('target', '')}"
        for e in edges
    )


def _format_conversation(history: list[dict], last_n: int = 10) -> str:
    """Include only the last N messages to save tokens."""
    recent = history[-last_n:] if len(history) > last_n else history
    if not recent:
        return "(no conversation yet)"
    lines = []
    for msg in recent:
        role = "선생님 (사용자)" if msg["role"] == "user" else "나 (학생)"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


# ── Main function ─────────────────────────────────────────

def generate_student_question(
    topic: str,
    student_context: dict,
    conversation_history: list[dict],
    model: str = "gpt-5.4-mini",
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
        confirmed_nodes = student_context.get("confirmed_nodes", [])
        partial_nodes   = student_context.get("partial_nodes", [])
        has_prior_knowledge = bool(confirmed_nodes or partial_nodes)

        if has_prior_knowledge:
            confirmed_edges = student_context.get("confirmed_edges", [])
            partial_edges   = student_context.get("partial_edges", [])
            user_prompt = _STUDENT_RETURNING_TEMPLATE.format(
                topic=topic,
                confirmed_nodes=", ".join(confirmed_nodes) if confirmed_nodes else "(없음)",
                partial_nodes=", ".join(partial_nodes)     if partial_nodes   else "(없음)",
                confirmed_edges=_format_edges(confirmed_edges),
                partial_edges=_format_edges(partial_edges),
            )
        else:
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

    print("\n" + "="*60)
    print("[Student] USER PROMPT →")
    print(user_prompt)
    print("="*60 + "\n")

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": STUDENT_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.6,
    )

    question = response.choices[0].message.content.strip()

    print("\n" + "="*60)
    print("[Student] RAW RESPONSE →")
    print(question)
    print("="*60 + "\n")

    logger.info("Student question — %s", question[:80])
    return StudentResponse(question=question)


def generate_session_closing_message(
    topic: str,
    termination_reason: str,
    session_summary: dict,
    model: str = "gpt-5.4-mini",
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
