"""
services/evaluator_llm.py
--------------------------
Evaluator LLM 에이전트.

역할:
  - 사용자의 설명을 RAG 기반 학습자료와 비교해 4개 영역 루브릭 채점
  - User KG를 업데이트 (confirmed / partial / missing / misconception 판정)
  - 세션 종료 여부 판단 (총점 10점 이상 or 반복 한계 or 턴 수 초과)

[변경 이력]
  - RelationType 및 EdgeStatus.MISCONCEPTION import 추가
  - _EVALUATOR_SYSTEM_PROMPT에 허용 relation 타입 목록 명시
  - _EVALUATOR_USER_TEMPLATE에 reference 엣지의 relation 타입 노출
  - updated_user_kg.edges 스키마에 misconception 상태 추가
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
from openai import OpenAI

from app.config import settings
from app.services.kg_service import (
    EdgeStatus,
    NodeStatus,
    RelationType,
    _RELATION_TYPE_GUIDE,
    get_missing_nodes,
    get_nodes_by_status,
)

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=settings.openai_api_key)

# ── 세션 종료 임계값 ───────────────────────────────────────
SCORE_THRESHOLD = 10
MAX_TURNS = 10
REPETITION_WINDOW = 3
REPETITION_MAX_SCORE = 2
SCORE_CATEGORIES = ["concept", "accuracy", "logic", "specificity"]


# ── 데이터 클래스 ──────────────────────────────────────────

@dataclass
class RubricScores:
    concept: int = 0
    accuracy: int = 0
    logic: int = 0
    specificity: int = 0

    @property
    def total(self) -> int:
        return self.concept + self.accuracy + self.logic + self.specificity

    def to_dict(self) -> dict:
        return {
            "concept": self.concept,
            "accuracy": self.accuracy,
            "logic": self.logic,
            "specificity": self.specificity,
        }


@dataclass
class EvaluatorResult:
    scores: RubricScores
    total: int
    is_sufficient: bool  # True → 세션 종료
    termination_reason: Optional[str]  # "score" | "repetition" | "turn_limit" | None
    updated_user_kg: dict  # kg_service.update_user_kg_from_evaluator() 입력용
    misconceptions: list[dict] = field(default_factory=list)


# ── 프롬프트 ──────────────────────────────────────────────

_EVALUATOR_SYSTEM_PROMPT = """\
당신은 페인만 기법 기반 학습 서비스의 Evaluator LLM입니다.

===역할===
1. 학습자가 제출한 개념 설명을 학습자료(RAG 청크)와 Reference KG를 기준으로 평가합니다.
2. 4개 루브릭 영역을 채점합니다.
3. 사용자 설명에서 개념과 관계를 추출해 User KG 업데이트 정보를 생성합니다.
4. 오개념이 있으면 기록합니다.

=== 루브릭 채점 기준 (각 0~3점) ===
- concept    : 0=핵심 개념 거의 없음, 1=일부만 포함, 2=대부분 포함, 3=빠짐없이 포함
- accuracy   : 0=핵심 오류 존재, 1=모호한 부분 많음, 2=전반적으로 정확(세부 부족), 3=핵심·세부 모두 정확
- logic      : 0=문장 나열 수준, 1=부분적 연결만, 2=흐름은 있으나 일부 비약, 3=원인-과정-결과 자연스럽게 연결
- specificity: 0=추상적 표현만, 1=약간의 구체화, 2=구체적 표현 포함, 3=예시·적용 상황까지 제시

=== 체크리스트 기반 노드 평가 방법 ===
Reference KG의 각 노드에는 체크리스트 항목이 있습니다.
사용자의 설명이 해당 노드의 체크리스트 항목을 얼마나 충족하는지 기준으로 아래 상태를 판정하세요.

=== User KG 노드 상태 정의 ===
- confirmed    : 노드를 언급했고, 체크리스트 항목을 모두 충족함
- partial      : 노드를 언급했지만, 체크리스트 항목 중 일부만 충족함 (모순 없음)
- misconception: 노드를 언급했지만, 체크리스트 항목과 RAG 자료에 명백히 모순되는 설명 존재
- missing      : 노드를 언급하지 않음 (이번 턴 + 누적 User KG에서 모두 미언급)

=== User KG 엣지 상태 정의 ===
- confirmed    : 두 개념 사이의 관계를 relation 타입에 맞게 정확하게 설명함
- partial      : 관계를 언급했지만 설명이 불완전하거나 relation 타입이 모호함
- missing      : 관계를 아직 설명하지 않음
- misconception: 관계 방향이 역전됐거나 잘못된 relation 타입으로 설명함
                 예) Reference: TCP -[포함한다]-> 흐름 제어
                     사용자: "흐름 제어가 TCP를 포함한다" → 방향 역전 → misconception

=== 엣지 relation 규칙 ===
updated_user_kg의 edges에서 relation은 반드시 아래 허용 목록 중 하나만 사용하세요.

""" + _RELATION_TYPE_GUIDE + """

=== 중요 규칙 ===
- updated_user_kg에는 이번 설명에서 언급된 노드/엣지만 포함합니다.
- Reference KG에 없는 개념을 사용자가 잘못 서술했다면 misconceptions에 기록하세요.
- 반드시 순수 JSON만 반환하세요. 마크다운·설명 텍스트 없이.
"""

_EVALUATOR_USER_TEMPLATE = """\
=== 학습 자료 (RAG 검색 결과) ===
{rag_context}

=== Reference KG (평가 기준 — 이 문서에서 추출된 실제 개념 구조) ===
노드 목록 (각 노드의 [체크리스트] 항목 충족 여부로 confirmed/partial 판정):
{reference_nodes}
엣지 목록 : {reference_edges}

  ※ 엣지 형식: source -[relation]-> target
     relation은 위 허용 목록(포함한다/구성요소이다/종류이다/사용한다/전제한다/
     가능하게 한다/야기한다/특성을 가진다/예시이다) 중 하나입니다.
     사용자의 설명이 이 relation과 방향을 정확히 반영하는지 판단하세요.

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
      {{"id": "<Reference KG 노드 중 이번 설명에서 언급된 것>", "status": "confirmed|partial|missing"}}
    ],
    "edges": [
      {{
        "source": "<노드>",
        "relation": "<허용 목록 9개 중 하나>",
        "target": "<노드>",
        "status": "confirmed|partial|missing|misconception"
      }}
    ]
  }},
  "misconceptions": [
    {{"content": "<사용자의 잘못된 설명>", "correction": "<올바른 설명>"}}
  ]
}}
"""


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _build_rag_context(rag_chunks: list[str]) -> str:
    if not rag_chunks:
        return "(검색된 학습자료 없음)"
    return "\n\n".join(f"[청크 {i + 1}]\n{chunk}" for i, chunk in enumerate(rag_chunks))


def _kg_to_prompt_strings(kg: nx.DiGraph) -> tuple[str, str]:
    """
    Reference KG의 노드/엣지를 프롬프트 삽입용 문자열로 변환한다.
    노드에 checklist가 있으면 항목을 함께 출력해 Evaluator LLM이
    체크리스트 기반으로 confirmed/partial 판정할 수 있게 한다.
    """
    node_lines = []
    for node_id, attrs in kg.nodes(data=True):
        if node_id == "__misconceptions__":
            continue
        checklist = attrs.get("checklist", [])
        if checklist:
            items = " | ".join(
                f"({i + 1}) {ck.get('item', '')}"
                for i, ck in enumerate(checklist)
            )
            node_lines.append(f"{node_id} [체크리스트: {items}]")
        else:
            node_lines.append(node_id)

    edges = [
        f"{src} -[{attrs.get('relation', '?')}]-> {tgt}"
        for src, tgt, attrs in kg.edges(data=True)
    ]
    return (
        "\n".join(node_lines) if node_lines else "(노드 없음)",
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
    for scores in recent:
        if any(scores.get(cat, 0) > max_score for cat in SCORE_CATEGORIES):
            return False
    return True


def _parse_evaluator_json(raw: str) -> dict:
    """LLM 응답에서 JSON 파싱. 코드블록 제거 포함."""
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Evaluator JSON 파싱 실패: %s\n원본: %s", e, raw)
        raise ValueError(f"Evaluator LLM이 올바른 JSON을 반환하지 않았습니다: {e}") from e


# ── 메인 평가 함수 ─────────────────────────────────────────

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
        user_explanation : 이번 턴 사용자 설명 텍스트
        user_kg          : 현재 User KG (업데이트 전)
        reference_kg     : Reference KG (고정)
        rag_chunks       : pgvector 검색 결과 청크 목록
        session_history  : 이전 턴의 scores dict 리스트
        turn_count       : 현재 턴 번호 (1-indexed)
        model            : OpenAI 모델명
    """
    # ── 프롬프트 변수 구성 ──
    rag_context = _build_rag_context(rag_chunks)

    ref_nodes_str, ref_edges_str = _kg_to_prompt_strings(reference_kg)
    confirmed_nodes = ", ".join(get_nodes_by_status(user_kg, NodeStatus.CONFIRMED)) or "(없음)"
    partial_nodes = ", ".join(get_nodes_by_status(user_kg, NodeStatus.PARTIAL)) or "(없음)"
    missing_nodes = ", ".join(get_missing_nodes(user_kg)) or "(없음)"

    user_prompt = _EVALUATOR_USER_TEMPLATE.format(
        rag_context=rag_context,
        reference_nodes=ref_nodes_str,
        reference_edges=ref_edges_str,
        confirmed_nodes=confirmed_nodes,
        partial_nodes=partial_nodes,
        missing_nodes=missing_nodes,
        user_explanation=user_explanation,
    )

    logger.info("Evaluator 호출 — 턴 %d | RAG 청크 %d개", turn_count, len(rag_chunks))

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    data = _parse_evaluator_json(response.choices[0].message.content)

    # ── 점수 파싱 ──
    raw_scores = data.get("scores", {})
    scores = RubricScores(
        concept=int(raw_scores.get("concept", 0)),
        accuracy=int(raw_scores.get("accuracy", 0)),
        logic=int(raw_scores.get("logic", 0)),
        specificity=int(raw_scores.get("specificity", 0)),
    )
    total = scores.total

    # ── 세션 종료 판단 ──
    is_sufficient = False
    termination_reason = None

    if total >= SCORE_THRESHOLD:
        is_sufficient = True
        termination_reason = "score"
    elif turn_count >= MAX_TURNS:
        is_sufficient = True
        termination_reason = "turn_limit"
    elif _check_repetition_limit(session_history, REPETITION_WINDOW, REPETITION_MAX_SCORE):
        is_sufficient = True
        termination_reason = "repetition"

    logger.info(
        "Evaluator 결과 — 총점: %d/12 | 종료: %s(%s)",
        total, is_sufficient, termination_reason,
    )

    return EvaluatorResult(
        scores=scores,
        total=total,
        is_sufficient=is_sufficient,
        termination_reason=termination_reason,
        updated_user_kg=data.get("updated_user_kg", {"nodes": [], "edges": []}),
        misconceptions=data.get("misconceptions", []),
    )


# ── 세션 요약 ──────────────────────────────────────────────

def _generate_session_feedback(
        topic: str,
        session_history: list[dict],
        weak_areas: list[str],
        coverage_percent: float,
        model: str,
) -> str:
    """세션 전체 데이터를 바탕으로 학습자 피드백을 LLM으로 생성한다."""
    if not session_history:
        return ""

    avg_scores = {
        cat: round(sum(s.get(cat, 0) for s in session_history) / len(session_history), 1)
        for cat in SCORE_CATEGORIES
    }
    label_map = {
        "concept": "핵심 개념 포함도",
        "accuracy": "설명 정확도",
        "logic": "논리적 흐름",
        "specificity": "구체성·예시",
    }
    weak_str = ", ".join(label_map.get(w, w) for w in weak_areas) if weak_areas else "없음"

    prompt = f"""\
학습 주제: {topic}
전체 턴 수: {len(session_history)}
KG 커버리지: {coverage_percent}%
영역별 평균 점수(0~3): {avg_scores}
보완이 필요한 영역: {weak_str}

위 데이터를 바탕으로 학습자에게 전달할 세션 피드백을 3~5문장으로 작성하세요.
- 잘한 부분을 먼저 언급하세요.
- 보완이 필요한 영역을 구체적으로 짚어주세요.
- 다음 학습을 위한 조언으로 마무리하세요.
- 한국어로 작성하세요.
"""

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "당신은 파인만 학습법 서비스의 학습 코치입니다."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
    )
    return response.choices[0].message.content.strip()


def build_session_summary(
        session_history: list[dict],
        user_kg: nx.DiGraph,
        reference_kg: nx.DiGraph,
        termination_reason: str,
        topic: str,
        model: str = "gpt-4o-mini",
) -> dict:
    """세션 종료 시 요약 정보를 생성한다."""
    from app.services.kg_service import get_kg_coverage, get_missing_nodes

    score_trend = [
        sum(s.get(cat, 0) for cat in SCORE_CATEGORIES)
        for s in session_history
    ]

    coverage = get_kg_coverage(user_kg, reference_kg)

    if session_history:
        avg_scores = {
            cat: sum(s.get(cat, 0) for s in session_history) / len(session_history)
            for cat in SCORE_CATEGORIES
        }
        weak_areas = [cat for cat, avg in avg_scores.items() if avg <= 2.0]
    else:
        weak_areas = []

    feedback_summary = _generate_session_feedback(
        topic=topic,
        session_history=session_history,
        weak_areas=weak_areas,
        coverage_percent=coverage.get("coverage_percent", 0),
        model=model,
    )

    return {
        "termination_reason": termination_reason,
        "total_turns": len(session_history),
        "score_trend": score_trend,
        "final_score": score_trend[-1] if score_trend else 0,
        "coverage": coverage,
        "missing_nodes": get_missing_nodes(user_kg),
        "weak_areas": weak_areas,
        "feedback_summary": feedback_summary,
    }