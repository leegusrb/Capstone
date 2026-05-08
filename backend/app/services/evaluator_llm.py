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
    weak_areas: list[str] = field(default_factory=list)


# ── 프롬프트 ──────────────────────────────────────────────

_EVALUATOR_SYSTEM_PROMPT = """\
당신은 페인만 기법 기반 학습 서비스의 Evaluator LLM입니다.

역할:
1. 학습자가 제출한 개념 설명을 학습자료(RAG 청크)와 Reference KG를 기준으로 평가합니다.
2. 4개 루브릭 영역을 채점합니다.
3. 사용자 설명에서 개념과 관계를 추출해 User KG의 노드의 status와 relation의 정보를 업데이트합니다.
4. 노드별 체크리스트의 각 항목이 사용자 설명에서 충족(met)됐는지 판정합니다.
5. 오개념이 있으면 기록합니다.

━━━ 루브릭 채점 기준 (각 0~3점) ━━━
- concept    : 0=핵심 개념 거의 없음, 1=일부만 포함, 2=대부분 포함, 3=빠짐없이 포함
- accuracy   : 0=핵심 오류 존재, 1=모호한 부분 많음, 2=전반적으로 정확(세부 부족), 3=핵심·세부 모두 정확
- logic      : 0=문장 나열 수준, 1=부분적 연결만, 2=흐름은 있으나 일부 비약, 3=원인-과정-결과 자연스럽게 연결
- specificity: 0=추상적 표현만, 1=약간의 구체화, 2=구체적 표현 포함, 3=예시·적용 상황까지 제시

━━━ 노드 상태 판정 — 체크리스트 기반 (반드시 아래 4단계 순서대로 수행) ━━━

각 Reference 노드는 체크리스트(2~4개 항목)를 가집니다.
아래 4단계를 순서대로 수행한 뒤 노드 상태를 결정합니다.

노드 상태 정의:
| 상태          | 조건                                                                          |
|--------------|------------------------------------------------------------------------------|
| confirmed    | 노드 이름이 등장했고, 체크리스트 전체 항목 met                                   |
| partial      | 노드 이름이 등장했지만, 일부만 met (나열·열거로 이름만 언급된 경우 포함), 모순 없음   |
| misconception| 노드 이름이 등장했지만, 항목 중 RAG 자료와 명백히 모순되는 설명 존재               |
| missing      | 노드 이름 자체가 사용자 설명에 한 번도 등장하지 않음 → output에 포함하지 않음        |

[1단계] 노드 추출 (문자열 일치 기준 — 의미 해석 금지)
  사용자 설명에서 Reference KG 노드 목록의 nodes.id와 문자열이 일치하는 것을 빠짐없이 찾으세요.

  ▸ 노드 이름이 사용자 설명에 그대로 등장하면 문맥에 관계없이 무조건 추출합니다.
  ▸ 조사 처리: "A라는", "A를", "A가" → "A"를 하나의 노드로 인식
  ▸ 나열 처리: "A, B, C로 구성된다" → A·B·C 각각 독립 노드로 추출
              상위 개념의 설명 안에 나열됐더라도 각각 추출합니다.

  예) Reference KG 노드: [A, B, C, D]
      사용자 설명: "A는 B, C, D를 포함하는 개념이야."
      추출 결과: A, B, C, D → 4개 전부 포함

  → 추출된 노드만 updated_user_kg.nodes에 포함합니다.
  → 추출되지 않은 노드(missing)는 포함하지 마세요.

[2단계] 언급 유형 분류 (반드시 먼저 판단)
  추출된 각 노드를 아래 두 유형 중 하나로 분류하세요.

  ▸ 유형 A — 이름만 언급 (나열·열거)
    정의: 개념 이름이 등장했지만 해당 개념 자체에 대한 내용 서술이 없는 경우
    예)  "이 개념은 A, B, C로 구성된다" → A·B·C는 이름만 나열됨
    처리: 반드시 updated_user_kg.nodes에 포함, status=partial 확정, 모든 checklist_result met=false, completion_ratio=0.0
    ※ 이름이 나열된 노드는 missing이 아닙니다. 반드시 partial로 output에 포함하세요. 3단계만 건너뜁니다.

  ▸ 유형 B — 실제 설명
    정의: 해당 개념의 의미·특성·역할·원리 등을 문장으로 서술한 경우
    예)  "A는 ~한 역할을 하며, ~한 특성을 가진다"
    처리: 3단계 체크리스트 평가 진행

[3단계] 체크리스트 met 판정 (유형 B 노드에만 적용)
  각 체크리스트 항목의 source_quote를 판정 기준으로 삼아 사용자 설명과 1:1 대조하세요.
  - met=true  : 사용자 설명이 해당 항목의 source_quote 내용을 포함하거나 동등한 의미로 서술한 경우
  - met=false : source_quote에 해당하는 내용이 사용자 설명에 없거나 개념 이름만 등장한 경우
  completion_ratio = met=true 항목 수 ÷ 전체 항목 수

[4단계] status 결정 (체크리스트 결과에서 도출)
  - completion_ratio = 1.0 (전체 항목 met=true)  → confirmed
  - completion_ratio < 1.0 (하나라도 met=false), 자료와 모순 없음 → partial
  - 항목 중 RAG 자료와 명백히 모순되는 서술 → misconception

  「misconception vs partial 경계」
    불완전하지만 방향성이 맞으면 partial, 자료와 직접 모순이면 misconception.
    예 (partial)       : 개념에 대해 맞지만 불완전한 설명    — 방향성은 맞음
    예 (misconception) : 개념에 대해 자료와 반대되는 설명    — 자료와 직접 모순


━━━ 엣지 상태 판정 — 구조적 (체크리스트 적용 안 함) ━━━
| 상태          | 조건                                                                |
|--------------|--------------------------------------------------------------------|
| confirmed    | 관계 언급 ✅ AND 방향 일치 AND relation 타입 일치(또는 호환)           |
| partial      | 관계 언급 ✅ AND 방향 일치 AND relation 타입이 모호하지만 본질 유사     |
| misconception| 관계 언급 ✅ AND (방향 역전 OR 본질적으로 다른 타입)                    |
| missing      | 관계 미언급                                                          |


━━━ relation 타입 호환 그룹 ━━━
같은 그룹 내 혼용은 partial, 다른 그룹 간 혼용은 misconception 으로 판정합니다.
  · 구성/소속 : 포함한다 / 구성요소이다 / 종류이다       (전체-부분, 상위-하위)
  · 기능/동작 : 사용한다 / 전제한다 / 가능하게 한다 / 야기한다 (작동·인과)
  · 속성/예시 : 특성을 가진다 / 예시이다                  (서술적 관계)

━━━ 의미적 역관계 매핑 ━━━
일부 relation은 방향만 뒤집으면 의미가 동등한 쌍이 존재합니다.
사용자가 방향과 relation 타입을 함께 뒤집어 표현한 경우는 confirmed 로 처리하세요 (오개념 아님).

| 사용자 표현                   | Reference KG 표현            | 판정                  |
|------------------------------|-----------------------------|----------------------|
| B -[구성요소이다]-> A          | A -[포함한다]-> B            | confirmed (의미 동등)   |
| B -[예시이다]-> A              | A -[종류이다]-> B            | confirmed (의미 동등)   |
| B -[포함한다]-> A              | A -[포함한다]-> B            | misconception (방향 역전) |

━━━ 엣지 relation 규칙 ━━━
updated_user_kg의 edges에서 relation은 반드시 아래 허용 목록 중 하나만 사용하세요.

""" + _RELATION_TYPE_GUIDE + """

━━━ misconception 판정 범위 제한 (PDF §12-4) ━━━
misconception은 Reference KG에 존재하는 개념/관계에 대해 사용자가 잘못 설명한 경우에만 적용합니다.
Reference KG에 없는 개념을 사용자가 언급하더라도 평가 범위 밖이므로 User KG에 반영하지 않고 무시합니다.
이를 통해 자료에 포함되지 않은 내용을 오개념으로 잘못 판정하는 상황을 방지합니다.

━━━ 중요 규칙 ━━━
- updated_user_kg.nodes 에는 Reference KG에 존재하는 노드 중 이번 설명에서 언급된 것만 포함합니다.
- 각 노드에 반드시 checklist_result(항목별 met/unmet 판정)와 completion_ratio(met÷전체)를 함께 반환합니다.
- checklist_result의 item 텍스트는 입력으로 주어진 항목과 1:1 동일하게 유지하세요 (재작성 금지).
- 반드시 순수 JSON만 반환하세요. 마크다운·설명 텍스트 없이.
"""

_EVALUATOR_USER_TEMPLATE = """\
=== 학습 자료 (RAG 검색 결과) ===
{rag_context}

=== Reference KG — 노드별 체크리스트 ===
각 노드의 체크리스트 항목을 사용자 설명과 대조해 met(true)/unmet(false)을 판정하세요.
source_quote는 해당 항목의 met 판정 기준이 되는 학습 자료 원문입니다. 사용자 설명이 source_quote의 내용을 포함하거나 동등하게 서술했는지를 기준으로 met를 판정하세요.

{reference_nodes_with_checklist}

=== Reference KG — 엣지 ===
{reference_edges}

  ※ 엣지 형식: source -[relation]-> target
     사용자 설명에서 두 개념의 관계가 이 방향과 relation 타입을 정확히 반영하는지 판단하세요.

=== 현재 User KG 상태 (누적) ===
confirmed 노드 : {confirmed_nodes}
partial 노드   : {partial_nodes}
missing 노드   : {missing_nodes}

=== 사용자 설명 (이번 턴) ===
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
      {{
        "id": "<Reference KG 노드 중 이번 설명에서 언급된 것>",
        "status": "confirmed|partial|missing|misconception",
        "checklist_result": [
          {{"item": "<해당 노드 체크리스트 항목 원문>", "met": true|false}}
        ],
        "completion_ratio": 0.0~1.0
      }}
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
    {{"node": "<관련 노드 id, 옵션>", "content": "<사용자의 잘못된 설명>", "correction": "<올바른 설명>"}}
  ]
}}
"""


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _build_rag_context(rag_chunks: list[str]) -> str:
    if not rag_chunks:
        return "(검색된 학습자료 없음)"
    return "\n\n".join(f"[청크 {i + 1}]\n{chunk}" for i, chunk in enumerate(rag_chunks))


def _format_reference_kg_with_checklist(reference_kg: nx.DiGraph) -> str:
    """
    Reference KG의 모든 노드를 체크리스트 항목과 함께 펼쳐서 프롬프트에 삽입할 문자열로 만든다.

    출력 예:
        [노드: TCP]
          체크리스트:
            1. 연결 지향 방식임을 명시
               (출처: "TCP는 연결 지향(connection-oriented) 프로토콜이다.")
            2. 신뢰성 보장 메커니즘 언급
               (출처: "TCP는 손실된 패킷의 재전송과 순서 보장을 통해 ...")
    """
    if reference_kg.number_of_nodes() == 0:
        return "(Reference KG 노드 없음)"

    blocks = []
    for node_id, attrs in reference_kg.nodes(data=True):
        if node_id == "__misconceptions__":
            continue
        checklist = attrs.get("checklist", [])
        lines = [f"[노드: {node_id}]"]
        if checklist:
            lines.append("  체크리스트:")
            for idx, item in enumerate(checklist, start=1):
                item_text = item.get("item", "")
                source_quote = item.get("source_quote", "")
                lines.append(f"    {idx}. {item_text}")
                if source_quote:
                    lines.append(f'       (출처: "{source_quote}")')
        else:
            lines.append("  체크리스트: (없음 — 노드 언급 여부만으로 판정)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _format_reference_edges(reference_kg: nx.DiGraph) -> str:
    """Reference KG의 엣지를 'src -[relation]-> tgt' 한 줄 단위 문자열로 변환."""
    edges = [
        f"{src} -[{attrs.get('relation', '?')}]-> {tgt}"
        for src, tgt, attrs in reference_kg.edges(data=True)
    ]
    return "\n".join(edges) if edges else "(엣지 없음)"


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

    reference_nodes_with_checklist = _format_reference_kg_with_checklist(reference_kg)
    reference_edges = _format_reference_edges(reference_kg)
    confirmed_nodes = ", ".join(get_nodes_by_status(user_kg, NodeStatus.CONFIRMED)) or "(없음)"
    partial_nodes = ", ".join(get_nodes_by_status(user_kg, NodeStatus.PARTIAL)) or "(없음)"
    missing_nodes_str = ", ".join(get_missing_nodes(user_kg)) or "(없음)"

    user_prompt = _EVALUATOR_USER_TEMPLATE.format(
        rag_context=rag_context,
        reference_nodes_with_checklist=reference_nodes_with_checklist,
        reference_edges=reference_edges,
        confirmed_nodes=confirmed_nodes,
        partial_nodes=partial_nodes,
        missing_nodes=missing_nodes_str,
        user_explanation=user_explanation,
    )

    logger.info("Evaluator 호출 — 턴 %d | RAG 청크 %d개", turn_count, len(rag_chunks))

    print("\n" + "="*60)
    print("[Evaluator] USER PROMPT →")
    print(user_prompt)
    print("="*60 + "\n")

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    raw_response = response.choices[0].message.content
    print("\n" + "="*60)
    print("[Evaluator] RAW RESPONSE →")
    print(raw_response)
    print("="*60 + "\n")

    data = _parse_evaluator_json(raw_response)

    # ── completion_ratio 기반 status 강제 교정 ──
    for node in data.get("updated_user_kg", {}).get("nodes", []):
        checklist = node.get("checklist_result", [])
        if checklist:
            met_count = sum(1 for item in checklist if item.get("met", False))
            ratio = met_count / len(checklist)
            node["completion_ratio"] = ratio
            if node.get("status") == "confirmed" and ratio < 1.0:
                node["status"] = "partial"

    # ── 점수 파싱 ──
    raw_scores = data.get("scores", {})
    scores = RubricScores(
        concept=int(raw_scores.get("concept", 0)),
        accuracy=int(raw_scores.get("accuracy", 0)),
        logic=int(raw_scores.get("logic", 0)),
        specificity=int(raw_scores.get("specificity", 0)),
    )
    total = scores.total

    # ── 세션 종료 판단 (사용자 직접 종료만 허용) ──
    is_sufficient = False
    termination_reason = None

    weak_areas = [
        cat for cat in SCORE_CATEGORIES
        if raw_scores.get(cat, 0) <= 2
    ]

    logger.info(
        "Evaluator 결과 — 총점: %d/%d | 종료: %s(%s) | weak: %s",
        total, SCORE_THRESHOLD * (12 // SCORE_THRESHOLD),
        is_sufficient, termination_reason, weak_areas,
    )

    return EvaluatorResult(
        scores=scores,
        total=total,
        is_sufficient=is_sufficient,
        termination_reason=termination_reason,
        updated_user_kg=data.get("updated_user_kg", {"nodes": [], "edges": []}),
        misconceptions=data.get("misconceptions", []),
        weak_areas=weak_areas,
    )


# ── 세션 요약 ──────────────────────────────────────────────

def build_session_summary(
        session_history: list[dict],
        user_kg: nx.DiGraph,
        reference_kg: nx.DiGraph,
        termination_reason: str,
) -> dict:
    """세션 종료 시 요약 정보를 생성한다.

    node_progress 는 노드별 met/total 카운트와 completion_ratio만 포함하며,
    체크리스트 항목 텍스트는 노출하지 않는다 (PDF §12-5 학습 효과 보존).
    """
    from app.services.kg_service import (
        get_kg_coverage,
        get_missing_nodes,
        get_user_kg_view_for_session_summary,
    )

    score_trend = [
        sum(s.get(cat, 0) for cat in SCORE_CATEGORIES)
        for s in session_history
    ]

    return {
        "termination_reason": termination_reason,
        "total_turns": len(session_history),
        "score_trend": score_trend,
        "final_score": score_trend[-1] if score_trend else 0,
        "coverage": get_kg_coverage(user_kg, reference_kg),
        "missing_nodes": get_missing_nodes(user_kg),
        "node_progress": get_user_kg_view_for_session_summary(user_kg),
    }