"""
services/evaluator_llm.py
--------------------------
Evaluator LLM 에이전트.

역할:
  - 사용자의 설명을 RAG 기반 학습자료와 비교해 4개 영역 루브릭 채점
  - User KG를 업데이트 (confirmed / partial / missing / misconception 판정)
  - 세션 종료 여부 판단 (총점 10점 이상 or 반복 한계 or 턴 수 초과)
  - 다음 Student LLM이 던질 질문 힌트 생성

핵심 설계 원칙:
  - Reference KG / User KG 는 DB에서 로드한 실제 값을 그대로 사용
  - 프롬프트에 삽입되는 노드/엣지 목록은 모두 실제 KG에서 동적으로 추출
  - 고정 예시 문자열 없음
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

# ── 세션 종료 임계값 ───────────────────────────────────────
SCORE_THRESHOLD    = 10
MAX_TURNS          = 10
REPETITION_WINDOW  = 3
REPETITION_MAX_SCORE = 2
SCORE_CATEGORIES   = ["concept", "accuracy", "logic", "specificity"]


# ── 데이터 클래스 ──────────────────────────────────────────

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
    is_sufficient:      bool            # True → 세션 종료
    termination_reason: Optional[str]   # "score" | "repetition" | "turn_limit" | None
    updated_user_kg:    dict            # kg_service.update_user_kg_from_evaluator() 입력용
    misconceptions:     list[dict] = field(default_factory=list)
    weak_areas:         list[str]  = field(default_factory=list)
    feedback_summary:   str        = ""


# ── 프롬프트 ──────────────────────────────────────────────

_EVALUATOR_SYSTEM_PROMPT = """\
당신은 페인만 기법 기반 학습 서비스의 Evaluator LLM입니다.

역할:
1. 학습자가 제출한 개념 설명을 학습자료(RAG 청크)와 Reference KG를 기준으로 평가합니다.
2. 4개 루브릭 영역을 채점합니다.
3. 사용자 설명에서 개념과 관계를 추출해 User KG 업데이트 정보를 생성합니다.
4. 오개념이 있으면 기록합니다.

루브릭 채점 기준 (각 0~3점):
- concept    : 0=핵심 개념 거의 없음, 1=일부만 포함, 2=대부분 포함, 3=빠짐없이 포함
- accuracy   : 0=핵심 오류 존재, 1=모호한 부분 많음, 2=전반적으로 정확(세부 부족), 3=핵심·세부 모두 정확
- logic      : 0=문장 나열 수준, 1=부분적 연결만, 2=흐름은 있으나 일부 비약, 3=원인-과정-결과 자연스럽게 연결
- specificity: 0=추상적 표현만, 1=약간의 구체화, 2=구체적 표현 포함, 3=예시·적용 상황까지 제시

User KG 노드 상태 정의:
- confirmed    : 사용자가 정확하게 설명한 개념
- partial      : 언급됐지만 설명이 불완전하거나 관계가 모호함
- missing      : 아직 설명되지 않음 — 이번 설명에 등장하지 않으면 변경하지 마세요

중요 규칙:
- updated_user_kg 에는 이번 설명에서 언급된 노드/엣지만 포함합니다.
- Reference KG에 없는 개념을 사용자가 잘못 서술했다면 misconceptions에 기록하세요.
- 반드시 순수 JSON만 반환하세요. 마크다운·설명 텍스트 없이.
"""

# 노드·엣지 목록은 런타임에 실제 KG에서 추출해 삽입됩니다.
_EVALUATOR_USER_TEMPLATE = """\
=== 학습 자료 (RAG 검색 결과) ===
{rag_context}

=== Reference KG (평가 기준 — 이 문서에서 추출된 실제 개념 구조) ===
노드 목록 : {reference_nodes}
엣지 목록 : {reference_edges}

=== 현재 User KG 상태 ===
confirmed 노드 : {confirmed_nodes}
partial 노드   : {partial_nodes}
missing 노드   : {missing_nodes}

=== 사용자 설명 ===
{user_explanation}

=== 출력 형식 (순수 JSON만 반환) ===
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
      {{"id": "<위 Reference KG 노드 중 이번 설명에서 언급된 것>", "status": "confirmed|partial|missing"}}
    ],
    "edges": [
      {{"source": "<노드>", "relation": "<동사구>", "target": "<노드>", "status": "confirmed|partial|missing"}}
    ]
  }},
  "misconceptions": [
    {{"content": "<사용자의 잘못된 설명>", "correction": "<올바른 설명>"}}
  ],
  "weak_areas": ["concept|accuracy|logic|specificity 중 2점 이하인 영역"],
  "feedback_summary": "Student LLM이 다음 질문을 생성할 때 참고할 2~3문장 요약"
}}
"""


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _build_rag_context(rag_chunks: list[str]) -> str:
    if not rag_chunks:
        return "(검색된 학습자료 없음)"
    return "\n\n".join(f"[청크 {i+1}]\n{chunk}" for i, chunk in enumerate(rag_chunks))


def _kg_to_prompt_strings(kg: nx.DiGraph) -> tuple[str, str]:
    """
    실제 KG 그래프에서 노드/엣지를 추출해 프롬프트 삽입용 문자열로 변환한다.
    고정 예시 없이 업로드된 문서에서 생성된 KG 내용만 반영.
    """
    nodes = [
        f"{node_id}(status={attrs.get('status', '?')})"
        for node_id, attrs in kg.nodes(data=True)
        if node_id != "__misconceptions__"
    ]
    edges = [
        f"{src} -[{attrs.get('relation', '관련')}]-> {tgt}"
        for src, tgt, attrs in kg.edges(data=True)
    ]
    return (
        ", ".join(nodes) if nodes else "(노드 없음)",
        ", ".join(edges) if edges else "(엣지 없음)",
    )


def _check_repetition_limit(
    session_history: list[dict],
    window: int,
    max_score: int,
) -> bool:
    """최근 window 턴 동안 모든 카테고리 점수가 max_score 이하이면 True."""
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
        logger.error("Evaluator JSON 파싱 실패: %s\n원본: %s", e, raw)
        raise ValueError(f"Evaluator LLM이 올바른 JSON을 반환하지 않았습니다: {e}") from e


# ── 메인 함수 ─────────────────────────────────────────────

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
    사용자 설명을 평가하고 EvaluatorResult를 반환한다.

    Args:
        user_explanation : 사용자의 이번 턴 설명 텍스트
        user_kg          : DB에서 로드한 현재 User KG (nx.DiGraph)
        reference_kg     : DB에서 로드한 Reference KG (nx.DiGraph) — 업로드 문서 기반
        rag_chunks       : 이번 설명과 유사도 검색으로 가져온 실제 청크 텍스트 목록
        session_history  : 이전 턴의 scores dict 리스트
        turn_count       : 현재 턴 번호 (1-indexed)
        model            : OpenAI 모델명
    """
    # 실제 KG에서 동적으로 노드/엣지 추출
    ref_nodes_str, ref_edges_str = _kg_to_prompt_strings(reference_kg)

    confirmed_nodes = get_nodes_by_status(user_kg, NodeStatus.CONFIRMED)
    partial_nodes   = get_nodes_by_status(user_kg, NodeStatus.PARTIAL)
    missing_nodes   = get_missing_nodes(user_kg)

    user_prompt = _EVALUATOR_USER_TEMPLATE.format(
        rag_context=_build_rag_context(rag_chunks),
        reference_nodes=ref_nodes_str,
        reference_edges=ref_edges_str,
        confirmed_nodes=", ".join(confirmed_nodes) if confirmed_nodes else "(없음)",
        partial_nodes=", ".join(partial_nodes)   if partial_nodes   else "(없음)",
        missing_nodes=", ".join(missing_nodes)   if missing_nodes   else "(없음)",
        user_explanation=user_explanation,
    )

    logger.info(
        "Evaluator 호출 — 턴 %d | ref노드 %d개 | confirmed %d | partial %d | missing %d | 설명 %d자",
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

    # ── 세션 종료 조건 판단 ──
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
        "Evaluator 결과 — %s | 합계 %d | 종료 %s (%s)",
        scores.to_dict(), scores.total, is_sufficient, termination_reason,
    )
    return result


def build_session_summary(
    session_history: list[dict],
    user_kg: nx.DiGraph,
    reference_kg: nx.DiGraph,
    termination_reason: str,
) -> dict:
    """세션 종료 시 프론트엔드에 전달할 요약 dict를 생성한다."""
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