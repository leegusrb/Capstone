"""
services/student_llm.py
------------------------
Student LLM 에이전트.

역할:
  - "아무것도 모르는 학생" 페르소나로 사용자에게 질문한다.
  - User KG의 confirmed/partial 노드만 참조 가능 (missing은 접근·노출 금지).
  - Evaluator 결과의 feedback_summary와 weak_areas를 참고해 다음 질문을 생성한다.
  - 세션 시작 시 첫 질문(ice_breaker)도 생성한다.

핵심 설계 원칙:
  - 프롬프트에 삽입되는 모든 개념 목록은 실제 User KG에서 동적으로 추출
  - missing 노드는 프롬프트에 절대 포함하지 않음 (아키텍처 수준 차단)
  - topic도 학습자가 업로드한 문서와 세션 시작 시 입력한 값을 그대로 사용
"""

import json
import logging
from dataclasses import dataclass

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=settings.openai_api_key)


# ── 데이터 클래스 ──────────────────────────────────────────

@dataclass
class StudentResponse:
    question: str
    intent: str  # ice_breaker | clarify_partial | probe_depth | request_example | check_relation


# ── 프롬프트 ──────────────────────────────────────────────

_STUDENT_SYSTEM_PROMPT = """\
당신은 페인만 기법 학습 서비스의 학생 에이전트입니다.

페르소나:
- 해당 주제에 대해 완전히 처음 배우는 학생입니다.
- 사용자(선생님)가 설명해준 내용만 기억합니다.
- 아직 설명받지 못한 개념은 전혀 모릅니다. 절대 스스로 아는 척 하지 마세요.

질문 생성 규칙:
1. 한 번에 질문 1개만 합니다.
2. confirmed 개념은 "이해했어요" 식으로 가볍게 언급해도 됩니다.
3. partial 개념은 "좀 더 자세히 설명해 주실 수 있나요?" 식으로 이어갑니다.
4. 설명받지 않은 개념은 직접 언급하지 않습니다.
5. 친근하고 자연스러운 한국어로 작성합니다.
6. "네~", "아~", "그렇군요!" 같은 반응을 짧게 앞에 붙이면 더 자연스럽습니다.

질문 유형(intent):
- ice_breaker    : 세션 시작 첫 질문
- clarify_partial: partial 개념에 대한 추가 설명 요청
- probe_depth    : confirmed 개념의 작동 원리·이유를 더 깊이 탐구
- request_example: 구체적 예시나 적용 상황 요청
- check_relation : 두 개념 사이의 관계 확인

반드시 아래 JSON 형식으로만 응답하세요:
{
  "question": "질문 텍스트",
  "intent": "intent 태그"
}
"""

_STUDENT_FIRST_TURN_TEMPLATE = """\
=== 학습 주제 ===
{topic}

=== 상황 ===
지금 막 학습을 시작했습니다.
아직 선생님에게 아무 설명도 듣지 못했습니다.
주제에 대해 가장 기본적인 것부터 설명해달라는 첫 질문을 생성하세요.
topic 이름을 그대로 언급하되, "이게 뭔지", "어떤 건지" 수준의 열린 질문을 1개 만드세요.
"""

_STUDENT_FOLLOWUP_TEMPLATE = """\
=== 학습 주제 ===
{topic}

=== 내가 이해한 내용 (선생님이 설명해준 것만) ===
완전히 이해한 개념 : {confirmed_nodes}
부분적으로 이해한 개념 : {partial_nodes}
이해한 관계 : {confirmed_edges}
불완전하게 이해한 관계 : {partial_edges}

=== 평가자 피드백 (내부 참고 — 사용자에게 직접 말하지 말 것) ===
보완이 필요한 영역 : {weak_areas}
이번 설명 요약 : {feedback_summary}

=== 이번 세션 최근 대화 ===
{conversation_snippet}

=== 질문 생성 지침 ===
- partial 개념이 있으면 그것을 더 설명해달라는 질문을 우선합니다.
- weak_areas에 "specificity"가 있으면 구체적 예시를 요청하세요.
- weak_areas에 "logic"이 있으면 과정이나 순서를 질문하세요.
- weak_areas에 "accuracy"가 있으면 핵심 정의나 원리를 다시 확인하세요.
- weak_areas에 "concept"이 있으면 빠진 핵심 개념이 무엇인지 유도하세요.
- 모두 confirmed이고 partial이 없다면, 확인된 개념 중 하나를 더 깊이 탐구하세요.
- 이전 대화에서 이미 한 질문과 동일하거나 매우 유사한 질문은 하지 마세요.
- 질문은 단 1개만 생성하세요.
"""


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _format_edges(edges: list[dict]) -> str:
    if not edges:
        return "(없음)"
    return ", ".join(
        f"{e.get('source', '')} -[{e.get('relation', '')}]-> {e.get('target', '')}"
        for e in edges
    )


def _format_conversation(history: list[dict], last_n: int = 6) -> str:
    """최근 N개 대화만 포함해 토큰을 절약한다."""
    recent = history[-last_n:] if len(history) > last_n else history
    if not recent:
        return "(대화 없음)"
    lines = []
    for msg in recent:
        role = "선생님(사용자)" if msg["role"] == "user" else "나(학생)"
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
        logger.warning("Student JSON 파싱 실패, 텍스트 전체를 question으로 사용: %s", e)
        return {"question": raw.strip(), "intent": "probe_depth"}


# ── 메인 함수 ─────────────────────────────────────────────

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
    Student LLM이 다음 질문을 생성한다.

    Args:
        topic                : 사용자가 세션 시작 시 입력한 학습 주제 문자열
        student_context      : kg_service.get_student_context() 결과
                               confirmed/partial 노드·엣지만 포함, missing 없음
        conversation_history : 이번 세션의 전체 대화 기록
        evaluator_feedback   : Evaluator.feedback_summary (빈 문자열 = 첫 턴)
        weak_areas           : Evaluator.weak_areas
        missing_nodes        : get_missing_nodes() 결과 — 내부 로깅용, 프롬프트에 직접 넣지 않음
        model                : OpenAI 모델명
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
            confirmed_nodes=", ".join(confirmed_nodes) if confirmed_nodes else "(없음)",
            partial_nodes=", ".join(partial_nodes)     if partial_nodes   else "(없음)",
            confirmed_edges=_format_edges(confirmed_edges),
            partial_edges=_format_edges(partial_edges),
            weak_areas=", ".join(weak_areas)           if weak_areas      else "(없음)",
            feedback_summary=evaluator_feedback        if evaluator_feedback else "(없음)",
            conversation_snippet=_format_conversation(conversation_history),
        )

    logger.info(
        "Student 호출 — 첫 턴: %s | confirmed %d개 | partial %d개 | missing %d개(노출 안 함)",
        is_first_turn,
        len(student_context.get("confirmed_nodes", [])),
        len(student_context.get("partial_nodes", [])),
        len(missing_nodes),
    )

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _STUDENT_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    data = _parse_student_json(response.choices[0].message.content)

    result = StudentResponse(
        question=data.get("question", ""),
        intent=data.get("intent", "probe_depth"),
    )

    logger.info("Student 질문 — intent: %s | %s", result.intent, result.question[:80])
    return result


def generate_session_closing_message(
    topic: str,
    termination_reason: str,
    session_summary: dict,
    model: str = "gpt-4o-mini",
) -> str:
    """
    세션 종료 시 학생 에이전트의 마무리 메시지를 생성한다.

    Args:
        topic               : 학습 주제
        termination_reason  : "score" | "repetition" | "turn_limit" | "user"
        session_summary     : build_session_summary() 반환값
                              (final_coverage, missing_nodes 등 실제 값 포함)
        model               : OpenAI 모델명
    """
    coverage         = session_summary.get("final_coverage", {})
    missing          = session_summary.get("missing_nodes", [])
    coverage_percent = coverage.get("coverage_percent", 0)

    reason_comment_map = {
        "score":      "선생님 덕분에 많이 이해했어요!",
        "repetition": "조금 어렵게 느껴지는 부분이 있는 것 같아요. 학습 자료를 다시 살펴보면 도움이 될 것 같아요.",
        "turn_limit": "오늘 세션을 마무리할 시간이 됐어요.",
        "user":       "알겠어요, 오늘은 여기까지 할게요.",
    }
    reason_comment = reason_comment_map.get(termination_reason, "세션을 마칩니다.")

    missing_str = (
        f"'{', '.join(missing[:5])}'" + ("등" if len(missing) > 5 else "")
        if missing else "없음"
    )

    prompt = f"""\
학습 주제: {topic}
세션 종료 사유: {termination_reason} — {reason_comment}
KG 커버리지: {coverage_percent}% ({coverage.get('confirmed_count', 0)}/{coverage.get('total_count', 0)} 개념 설명 완료)
아직 설명 못 받은 개념: {missing_str}

학생 에이전트로서 자연스럽고 따뜻한 마무리 인사를 2~4문장으로 작성해주세요.
- 커버리지가 70% 이상이면 칭찬 위주로, 미만이면 격려 위주로 작성하세요.
- 미완료 개념이 있으면 다음 세션에서 들려달라고 제안하세요.
- 고정된 문구 없이 자연스럽게 작성하세요.
"""

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "당신은 페인만 기법 학습 서비스의 학생 에이전트입니다. 따뜻하고 격려하는 어조로 응답합니다.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()