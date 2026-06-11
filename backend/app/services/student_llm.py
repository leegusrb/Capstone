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
선생님의 설명을 듣는 학생입니다. 이 대화에서 선생님이 명시적으로 말한 내용만 알고 있으며, 외부 지식은 일절 없습니다. 
이 제약은 질문에도 동일하게 적용됩니다.

===질문 규칙===
1. 질문은 하나의 개념만, 1~2문장으로 제한합니다.
   나쁜 예: "A, B, C는 각각 무엇인가요?" / 좋은 예: "A는 무엇인가요?"
2. 칭찬하지 마세요.
3. 한국어, 친근하고 자연스러운 어조로 작성하세요.
4. confirmed 개념은 이미 이해한 것으로 간주해 다시 묻지 마세요.
5. 막연한 질문(예: "[개념]에 대해 자세히 설명해주세요")은 하지 마세요.
6. 선생님이 "모르겠다" 등 모른다는 표현을 하면: 자연스럽게 넘어간 뒤 직전과 다른 개념이나 관계를 질문하세요.
7. 질문 텍스트만 출력하세요.
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
- partial 개념이 있다면 해당 개념의 불명확한 부분을 우선 질문하세요.
- partial 개념이 없다면 이 학습 주제에서 아직 다루지 않은 내용이 있는지 열린 방식으로 물어보세요.
- "지난번에", "이어서" 같이 이전 세션을 자연스럽게 언급해도 좋습니다.
"""



_STUDENT_FOLLOWUP_TEMPLATE = """\
=== 학습 주제 ===
{topic}

=== 최근 대화 ===
{conversation_snippet}

━━━ 아래 순서대로 사고한 뒤 질문만 출력하세요 ━━━

[1단계: 발언 유형 파악]
선생님의 마지막 발언이 어떤 유형인지 구분하세요.

  유형 A — 예고 발언
    정의: "X에 대해 알아볼게요", "X를 설명할게요" 처럼 다음 내용을 선언만 하고 실제 설명은 없는 발언
    처리: [2단계]~[3단계]를 건너뛰고, 예고된 주제 X에 대한 첫 질문을 생성하세요.

  유형 B — 실제 설명
    정의: 개념의 의미·특성·원리·관계 등을 직접 서술한 발언
    처리: [2단계]로 진행하세요.

[2단계: 설명 내용 파악]
선생님이 방금 설명한 내용의 성격을 있는 그대로 파악하세요.
- 종류·분류 / 특징·속성 / 관계·차이 / 과정·예시 중 어느 것인가?
- ⚠ 선생님이 말하지 않은 단어(장점·단점·원인·결과 등)로 임의 재분류하지 마세요.

[3단계: 다음 질문 방향 결정]
아래 루브릭 신호를 확인하고, 해당 방향에 맞는 질문 유형을 결정하세요.

{direction_block}

[4단계: 질문 생성 및 검토]
[1]~[3]의 분석을 바탕으로 질문을 작성하고 출력하세요.
- 이미 선생님이 설명한 내용 재질문 금지
- 이전 턴의 질문 반복 금지
- 선생님이 언급하지 않은 새 개념 도입 금지 (새 내용 유도 방향은 열린 표현 허용)
- 질문의 의미가 자연스럽고 올바른지 확인 후 출력
"""


# ── Internal helpers ──────────────────────────────────────

def _compute_direction_block(
    coverage_ratio: float,
    confirmed_nodes: list[str],
    partial_nodes: list[str],
    confirmed_edges: list[dict],
    partial_edges: list[dict],
    low_confidence_nodes: list[str],
) -> str:
    """
    루브릭 신호를 우선순위(커버리지 → 논리성 → 구체성) 순으로 평가해
    다음 질문 방향을 결정한다. 방향은 LLM이 아닌 코드가 확정한다.
    """
    mentioned_count = len(confirmed_nodes) + len(partial_nodes)
    has_any_edge    = bool(confirmed_edges or partial_edges)

    # 1순위: 개념 커버리지 부족 → 다른 개념으로 유도
    if coverage_ratio < 0.5:
        already_mentioned = ", ".join(confirmed_nodes + partial_nodes) or "없음"
        return "\n".join([
            f"▶ 개념 커버리지 부족 [{int(coverage_ratio * 100)}%] → 아직 다루지 않은 내용을 유도하는 질문",
            f"  이미 설명된 개념 [{already_mentioned}]에 대한 추가·심화 질문 금지.",
            "  최근 설명한 내용과 자연스럽게 이어지는, 아직 다루지 않은 다른 내용을 열린 방식으로 유도하세요.",
        ])

    # 2순위: 논리성 — 언급된 개념 간 관계 미설명
    if mentioned_count >= 2 and not has_any_edge:
        node_list = ", ".join(confirmed_nodes + partial_nodes)
        return "\n".join([
            "▶ 논리성 부족 → 개념 간 관계를 묻는 질문",
            f"  설명된 개념: [{node_list}]",
            "  이 개념들 사이의 관계, 차이점, 또는 연결고리를 질문하세요.",
        ])

    # 3순위: 구체성 — confidence_level이 낮은 노드
    if low_confidence_nodes:
        node_list = ", ".join(low_confidence_nodes)
        return "\n".join([
            "▶ 구체성 부족 → 예시·과정을 묻는 질문",
            f"  대상 개념: [{node_list}]",
            "  이 개념이 실제로 어떻게 작동하는지, 구체적인 예시나 과정을 질문하세요.",
        ])

    # 기본: partial 보완 또는 브리징
    if partial_nodes:
        return "\n".join([
            "▶ 부분 이해 개념 보완 → 더 자세한 설명을 유도하는 질문",
            f"  대상 개념: [{', '.join(partial_nodes)}]",
            "  이 개념의 아직 설명되지 않은 측면을 질문하세요.",
        ])
    return "\n".join([
        "▶ 전반적 이해 양호 → 새 내용 유도",
        "  최근 설명한 내용에서 자연스럽게 이어지는 다른 내용이 있는지 열린 방식으로 유도하세요.",
    ])


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
        confirmed_nodes      = student_context.get("confirmed_nodes", [])
        partial_nodes        = student_context.get("partial_nodes", [])
        confirmed_edges      = student_context.get("confirmed_edges", [])
        partial_edges        = student_context.get("partial_edges", [])
        coverage_ratio       = student_context.get("coverage_ratio", 0.0)
        low_confidence_nodes = student_context.get("low_confidence_nodes", [])

        direction_block = _compute_direction_block(
            coverage_ratio, confirmed_nodes, partial_nodes,
            confirmed_edges, partial_edges, low_confidence_nodes,
        )

        user_prompt = _STUDENT_FOLLOWUP_TEMPLATE.format(
            topic=topic,
            direction_block=direction_block,
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
