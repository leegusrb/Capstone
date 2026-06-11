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
당신은 파인만 기법 기반 학습 서비스의 Evaluator LLM입니다.

역할: 사용자의 설명을 Reference KG 체크리스트와 비교해 met 여부를 판정하고, 노드 상태(confirmed/partial/misconception)를 결정합니다.

━━━ 핵심 원칙 ━━━
평가의 유일한 근거는 사용자 설명(=== 사용자 설명 === 아래 텍스트)입니다.
RAG 검색 결과와 Reference KG는 체크리스트 정답 기준으로만 사용합니다.
RAG나 Reference KG에 내용이 있어도, 사용자가 직접 서술하지 않았으면 met=false입니다.

━━━ 노드 상태 정의 ━━━
노드 상태는 노드 이름이 사용자 설명에 등장했는지가 아니라,
해당 노드의 체크리스트 항목 만족 결과로만 결정됩니다.

| 상태          | 조건                                                             |
|--------------|----------------------------------------------------------------|
| confirmed    | 체크리스트 전체 항목 met=true                                              |
| partial      | 1개 이상 met=true, 나머지 false / 또는 이름만 언급(모든 항목 met=false)     |
| misconception| RAG 자료와 명백히 모순되는 설명 존재                                        |
| missing      | 이름 미등장 AND 모든 항목 met=false → output에 포함하지 않음                |


━━━ 평가 절차 (반드시 이 순서대로 수행) ━━━

[준비 단계] 사용자 설명 절(clause) 분석
평가 전, 사용자 설명 전체를 한국어 연결 어미 기준으로 절 단위로 분리하고
각 절의 주어(어떤 개념)와 서술(무슨 내용)을 파악합니다.

  한국어 연결 어미 분류:
  · 대등적 연결 어미 — 앞뒤 절이 독립적이고 동등한 관계
      나열: -고, -며
      대조: -지만, -(으)나, -(으)ㄴ데
      선택: -거나, -든지

  · 종속적 연결 어미 — 앞 절이 뒤 절에 종속(원인·조건·목적)
      원인·이유: -어서/-아서, -니, -니까
      조건·가정: -(으)면
      목적·의도: -러, -려고

  · 보조적 연결 어미 — 본용언+보조용언 연결, 하나의 절로 취급
      -아/-어, -고, -지

  예시:
    입력: "DMLP는 모든 노드가 연결되어 있어서 복잡도가 높은데,
           CNN은 컨볼루션 연산을 사용해서 일부만 연결하는 구조라 복잡도가 낮아요."
    결과:
      절1 — 주어: DMLP / 서술: 모든 노드 연결 → 복잡도 높음
      절2 — 주어: CNN  / 서술: 컨볼루션 연산, 부분 연결 → 복잡도 낮음

[1단계] 체크리스트 항목별 만족 여부 판정
Reference KG의 모든 노드를 순서대로 검토합니다.
각 노드의 체크리스트 항목마다, [준비 단계]에서 분석한 모든 절들과 비교합니다.

  ① 사용자의 어떤 절이든 해당 체크리스트 항목(source_quote)의 핵심 사실을 서술하면 → 해당 체크리스트 항목의met=true
  ② 어떤 절도 해당 항목의 내용을 서술하지 않으면 → met=false (변경하지 않음)

  met=true 허용 기준 — 표현이 달라도 내용이 동일하면 인정:
  - 어순·조사·어미 차이:    "배당을 받는다" ≈ "배당을 받을 권리를 지닌다"
  - 능동↔수동 전환:         "기업이 지급한다" ≈ "주주가 받는다"
  - 동의어·유사어:           "의결권이 없다" ≈ "투표권을 갖지 못한다"
  - 풀어 쓴 표현:            "완전연결 구조" ≈ "모든 노드가 연결되어 있어서"

  met=false 확정:
  - 해당 항목의 핵심 사실이 사용자 설명 어디에도 없는 경우
  - RAG/Reference KG에는 있지만 사용자가 직접 서술하지 않은 경우

[2단계] 노드 상태 결정
각 노드의 체크리스트 결과와 이름 언급 여부를 함께 고려합니다.
  - 모든 항목 met=true                                              → confirmed, output에 포함
  - 1개 이상 met=true, 나머지 met=false                             → partial, output에 포함
  - 모든 항목 met=false, 단 노드 이름이 사용자 설명에 등장           → partial (completion_ratio=0.0), output에 포함
  - 모든 항목 met=false AND 노드 이름도 사용자 설명에 없음           → output에 포함하지 않음 (missing 유지)
  - 체크리스트 항목 중 RAG 자료와 명백히 모순되는 서술 존재          → misconception

  ⚠ 이미 confirmed 상태인 노드는 이번 설명에서 misconception으로 변경하지 마세요.
    오개념이 발견되면 misconceptions 배열에만 기록하고 status는 유지하세요.

[3단계] 체크리스트 외 오개념 검출
사용자 설명 전체를 RAG 자료와 비교합니다.
체크리스트 항목과 무관하더라도 RAG 자료와 명백히 상충하는 진술은 misconceptions 배열에 기록합니다.
  ✅ 기록: RAG가 "X다"인데 사용자가 "X가 아니다" 또는 사실과 다른 내용을 서술한 경우
  ❌ 제외: 불완전·생략·단순 미언급, Reference KG에 없는 개념


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
misconception은 Reference KG에 존재하는 노드의 체크리스트/관계에 대해 사용자가 잘못 설명한 경우에만 적용합니다.


━━━ 중요 규칙 ━━━
- 각 노드에 반드시 checklist_result(항목별 met/unmet 판정)와 completion_ratio(met÷전체)를 함께 반환합니다.
- checklist_result의 item 텍스트는 입력으로 주어진 항목과 1:1 동일하게 유지하세요 (재작성 금지).
- 반드시 순수 JSON만 반환하세요. 마크다운·설명 텍스트 없이.
"""

_EVALUATOR_USER_TEMPLATE = """\
=== 사용자 설명 (이번 턴) — 모든 판정의 유일한 근거 ===
⚠ 아래 텍스트만이 사용자가 이번 턴에 직접 말한 내용입니다.
체크리스트 met 판정은 반드시 아래 텍스트에서만 근거를 찾아야 합니다.
RAG 자료나 Reference KG에 같은 내용이 있어도, 사용자가 직접 서술하지 않았으면 met=false입니다.

{user_explanation}

=== 현재 User KG 상태 (누적) ===
confirmed 노드 : {confirmed_nodes}
partial 노드   : {partial_nodes}
missing 노드   : {missing_nodes}

=== Reference KG — 노드 ID 목록 ===
아래 목록이 이번 평가 대상인 Reference KG의 전체 노드입니다.
각 노드의 체크리스트 항목을 사용자 설명과 비교해 met 여부를 판정하세요.
노드 이름이 사용자 설명에 그대로 등장하지 않아도 됩니다.
체크리스트 항목의 내용을 사용자가 다른 표현으로 서술한 경우도 met=true로 인정합니다.

{reference_node_ids}

=== Reference KG — 노드별 체크리스트 ===
각 노드의 체크리스트 항목을 위의 사용자 설명과 대조해 met(true)/unmet(false)을 판정하세요.

{reference_nodes_with_checklist}

=== Reference KG — 엣지 ===
{reference_edges}

  ※ 엣지 형식: source -[relation]-> target
     사용자 설명에서 두 개념의 관계가 이 방향과 relation 타입을 정확히 반영하는지 판단하세요.

=== 학습 자료 (RAG 검색 결과 — 체크리스트 정답 기준용, 사용자 설명 아님) ===
※ 이 내용은 체크리스트 항목의 정답 기준입니다. 사용자가 말한 내용이 아닙니다.

{rag_context}

=== 출력 형식 (순수 JSON만 반환) ===
※ nodes 배열 포함 기준:
  - 체크리스트 항목이 1개 이상 met=true인 노드 → 포함
  - 노드 이름이 사용자 설명에 등장한 노드 → 포함 (모든 항목 met=false여도 partial로 포함)
  - 이름도 없고 모든 항목 met=false인 노드 → 포함하지 않음
{{
  "updated_user_kg": {{
    "nodes": [
      {{
        "id": "<체크리스트 항목 중 1개 이상 met=true인 Reference KG 노드>",
        "status": "confirmed|partial|misconception",
        "checklist_result": [
          {{"item": "<체크리스트 항목 원문 그대로>", "met": true|false}}
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
