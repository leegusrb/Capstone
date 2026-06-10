"""
services/evaluator_llm.py
--------------------------
Evaluator LLM 에이전트.

역할:
  - 사용자의 설명을 RAG 기반 학습자료와 비교해 User KG 업데이트
  - 구체성(specificity) 4개 기준 판정 (true/false)
  - User KG 누적 상태 기반으로 루브릭 4개 영역 점수 자동 계산
  - 세션 종료 여부 판단 (누적 총점 10점 이상)
"""

import json
import logging
from dataclasses import dataclass, field

import networkx as nx
from openai import OpenAI

from app.config import settings
from app.services.kg_service import (
    NodeStatus,
    _RELATION_TYPE_GUIDE,
    get_missing_nodes,
    get_nodes_by_status,
    is_evaluation_node,
)
from app.services.rubric_service import SCORE_CATEGORIES

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=settings.openai_api_key)

@dataclass
class EvaluatorResult:
    updated_user_kg: dict
    misconceptions: list[dict] = field(default_factory=list)


# ── 프롬프트 ──────────────────────────────────────────────

_EVALUATOR_SYSTEM_PROMPT = """\
당신은 페인만 기법 기반 학습 서비스의 Evaluator LLM입니다.

역할:
1. 학습자가 제출한 개념 설명을 학습자료(RAG 청크)와 Reference KG를 기준으로 평가합니다.
2. 사용자 설명에서 개념과 관계를 추출해 User KG의 노드의 status와 relation의 정보를 업데이트합니다.
3. 노드별 체크리스트의 각 항목이 사용자 설명에서 충족(met)됐는지 판정합니다.
4. 오개념이 있으면 기록합니다.

※ 루브릭 점수는 시스템이 User KG 누적 상태로부터 자동 계산합니다. 직접 점수를 매기지 마세요.

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
  각 체크리스트 항목에 대해 아래 두 단계를 순서대로 적용하세요.

  [1차 판정] source_quote 직접 대조
    사용자 설명이 source_quote의 내용을 그대로 포함하거나 매우 유사한 표현으로 서술했는가?
    → 해당하면 met=true 확정

  [2차 판정] 의미적 동등성 확인 (1차에서 false인 경우에만 적용)
    사용자 설명이 source_quote와 표현은 다르지만 동일한 개념·원리·사실을 전달하고 있는가?
    → 해당하면 met=true
    → 해당하지 않으면 met=false

  - met=false 조건: source_quote의 내용이 사용자 설명에 전혀 없거나, 개념 이름만 등장한 경우
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

━━━ misconception 판정 범위 제한 ━━━
misconception은 Reference KG에 존재하는 개념/관계에 대해 사용자가 잘못 설명한 경우에만 적용합니다.
Reference KG에 없는 개념을 사용자가 언급하더라도 평가 범위 밖이므로 User KG에 반영하지 않고 무시합니다.

━━━ 중요 규칙 ━━━
- updated_user_kg.nodes 에는 Reference KG에 존재하는 노드 중 이번 설명에서 언급된 것만 포함합니다.
- 각 노드에 반드시 checklist_result(항목별 met/unmet 판정)와 completion_ratio(met÷전체)를 함께 반환합니다.
- checklist_result의 item 텍스트는 입력으로 주어진 항목과 1:1 동일하게 유지하세요 (재작성 금지).
- 반드시 순수 JSON만 반환하세요. 마크다운·설명 텍스트 없이.
"""

_EVALUATOR_USER_TEMPLATE = """\
=== 학습 자료 (RAG 검색 결과) ===
{rag_context}

=== Reference KG — 노드 ID 목록 (문자열 일치 기준) ===
아래 목록은 이번 평가 대상인 Reference KG의 전체 노드 ID입니다.
사용자 설명에서 이 목록에 있는 문자열이 그대로 등장하는 노드만 추출하세요.
목록에 없는 개념은 평가 대상이 아닙니다.

{reference_node_ids}

=== Reference KG — 노드별 체크리스트 ===
각 노드의 체크리스트 항목을 사용자 설명과 대조해 met(true)/unmet(false)을 판정하세요.

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
    if reference_kg.number_of_nodes() == 0:
        return "(Reference KG 노드 없음)"

    blocks = []
    for node_id, attrs in reference_kg.nodes(data=True):
        if not is_evaluation_node(node_id, attrs):
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
    edges = [
        f"{src} -[{attrs.get('relation', '?')}]-> {tgt}"
        for src, tgt, attrs in reference_kg.edges(data=True)
        if (
            is_evaluation_node(src, reference_kg.nodes[src])
            and is_evaluation_node(tgt, reference_kg.nodes[tgt])
        )
    ]
    return "\n".join(edges) if edges else "(엣지 없음)"


def _parse_evaluator_json(raw: str) -> dict:
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
        turn_count: int,
        model: str = "gpt-5.4-mini",
) -> EvaluatorResult:
    """
    사용자 설명을 평가하고 EvaluatorResult를 반환한다.

    루브릭 점수는 LLM이 아닌 시스템이 계산한다:
      - LLM: updated_user_kg (노드/엣지 상태), misconceptions, specificity_checklist 반환
      - 시스템: 이번 턴 업데이트를 반영한 누적 KG 상태로 concept/accuracy/logic 계산
               specificity_checklist true 개수로 specificity 계산
    """
    rag_context = _build_rag_context(rag_chunks)
    reference_node_ids = "\n".join(
        f"- {n}" for n in reference_kg.nodes()
        if not str(n).startswith("__")
    )
    reference_nodes_with_checklist = _format_reference_kg_with_checklist(reference_kg)
    reference_edges = _format_reference_edges(reference_kg)
    confirmed_nodes = ", ".join(get_nodes_by_status(user_kg, NodeStatus.CONFIRMED)) or "(없음)"
    partial_nodes = ", ".join(get_nodes_by_status(user_kg, NodeStatus.PARTIAL)) or "(없음)"
    missing_nodes_str = ", ".join(get_missing_nodes(user_kg)) or "(없음)"

    user_prompt = _EVALUATOR_USER_TEMPLATE.format(
        rag_context=rag_context,
        reference_node_ids=reference_node_ids,
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
        temperature=0.0,
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

    logger.info("Evaluator 결과 — 턴 %d 완료", turn_count)

    return EvaluatorResult(
        updated_user_kg=data.get("updated_user_kg", {"nodes": [], "edges": []}),
        misconceptions=data.get("misconceptions", []),
    )


# ── 루브릭 평가 (confidence_level) ────────────────────────

_CONFIDENCE_SYSTEM_PROMPT = """\
당신은 학습자의 개념 설명 품질을 평가하는 루브릭 평가 LLM입니다.

역할:
주어진 노드(개념) 목록 각각에 대해, 학습자가 해당 개념을 얼마나 확신 있게 설명했는지를
"high" / "medium" / "low" 중 하나로 판정합니다.

판정 기준:

▸ high — 확신 있는 설명
  아래 중 하나 이상 해당:
  - 구체적 수치·고유명사·프로토콜명·알고리즘명 포함
    예) "3-way handshake", "ACK 패킷", "64비트", "FIFO 방식"
  - 인과관계나 동작 원리를 능동적 문장으로 서술
    예) "A가 발생하면 B가 트리거되어 C 상태가 된다"
  - 예시나 구체적 시나리오를 직접 제시하며 설명

▸ medium — 부분적 확신
  아래 중 하나 이상 해당:
  - 핵심 내용은 서술했지만 불확실 표현 혼재
  - 개념의 일부만 서술하고 나머지 생략
  - "~인 것 같아요"가 일부 있지만 전반적으로 내용은 갖춰진 경우

▸ low — 불확실한 설명
  아래 중 하나 이상 해당:
  - 추측성 표현: "아마", "~것 같은데", "맞는지 모르겠지만"
  - 확인 요청: "이게 맞나요?", "~아닌가요?"
  - 이름만 언급하고 의미 서술 없음
  - 부정적 자기평가: "잘 모르겠어요", "기억이 잘 안 나요"

주의:
- 각 노드를 설명하는 부분만 기준으로 판정하고 문장 전체를 기준으로 삼지 마세요.
- 반드시 순수 JSON만 반환하세요.
"""

_CONFIDENCE_USER_TEMPLATE = """\
=== 학습 자료 (RAG 검색 결과) ===
{rag_context}

=== 평가 대상 노드 목록 ===
{node_ids}

=== 사용자 설명 ===
{user_explanation}

=== 출력 형식 (순수 JSON만 반환) ===
{{
  "confidence_levels": {{
    "<노드 id>": "high|medium|low"
  }}
}}
"""


def evaluate_confidence_levels(
    user_explanation: str,
    mentioned_node_ids: list[str],
    rag_chunks: list[str],
    model: str = "gpt-5.4-mini",
) -> dict[str, str]:
    """
    언급된 노드별 confidence_level을 별도 LLM 호출로 평가한다.
    """
    if not mentioned_node_ids:
        return {}

    rag_context = _build_rag_context(rag_chunks)
    node_ids_str = "\n".join(f"- {nid}" for nid in mentioned_node_ids)

    user_prompt = _CONFIDENCE_USER_TEMPLATE.format(
        rag_context=rag_context,
        node_ids=node_ids_str,
        user_explanation=user_explanation,
    )

    logger.info("Confidence 평가 호출 — 노드 %d개", len(mentioned_node_ids))

    print("\n" + "="*60)
    print("[Confidence] USER PROMPT →")
    print(user_prompt)
    print("="*60 + "\n")

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _CONFIDENCE_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()

    print("\n" + "="*60)
    print("[Confidence] RAW RESPONSE →")
    print(raw)
    print("="*60 + "\n")

    try:
        data = json.loads(raw)
        return data.get("confidence_levels", {})
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Confidence 평가 파싱 실패: %s", e)
        return {nid: "low" for nid in mentioned_node_ids}


# ── 세션 요약 ──────────────────────────────────────────────

def build_session_summary(
        session_history: list[dict],
        user_kg: nx.DiGraph,
        reference_kg: nx.DiGraph,
        termination_reason: str,
) -> dict:
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
