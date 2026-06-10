"""
services/rubric_service.py
--------------------------
루브릭 평가 서비스.

역할:
  - 루브릭 4개 영역(concept, accuracy, logic, specificity) 점수 계산
  - 노드별 confidence_level LLM 평가 (specificity 루브릭용)

점수 기준:
  concept    : ((1.0 * confirmed) + (0.5 * partial)) / 전체 ref 노드
  accuracy   : ((1.0 * confirmed) + (0.5 * partial)) / 언급 노드 (오개념 패널티)
  logic      : ((1.0 * confirmed_edge) + (0.5 * partial_edge)) / 언급 엣지
  specificity: 노드별 confidence_level 가중 평균 (high=1.0, medium=0.5, low=0.0)
"""

import json
import logging
from dataclasses import dataclass

import networkx as nx
from openai import OpenAI

from app.config import settings
from app.services.kg_service import (
    EdgeStatus,
    NodeStatus,
    get_edges_by_status,
    get_nodes_by_status,
)

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=settings.openai_api_key)

# ── 상수 ──────────────────────────────────────────────────

SCORE_THRESHOLD = 10
MAX_TURNS = 10
SCORE_CATEGORIES = ["concept", "accuracy", "logic", "specificity"]

_CONFIDENCE_SCORE    = {"high": 1.0, "medium": 0.5, "low": 0.0}
_CONFIDENCE_PRIORITY = {"high": 2,   "medium": 1,   "low": 0}


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
            "concept":     self.concept,
            "accuracy":    self.accuracy,
            "logic":       self.logic,
            "specificity": self.specificity,
        }


# ── 루브릭 점수 계산 ───────────────────────────────────────

def compute_rubric_scores(
    user_kg: nx.DiGraph,
    reference_kg: nx.DiGraph,
) -> RubricScores:
    """
    User KG 누적 상태로부터 루브릭 4개 영역 점수를 계산한다.

    점수 기준:
      concept    : ((1.0 * confirmed) + (0.5 * partial)) / 전체 ref 노드
                   ratio≥0.7→3 / ratio≥0.4→2 / ratio≥0.2→1 / else→0
      accuracy   : ((1.0 * confirmed) + (0.5 * partial)) / (confirmed + partial + misconception) (오개념 패널티)
                   ratio≥0.7 & misc=0→3 / ratio≥0.4 & misc≤1→2 / ratio≥0.2 & misc≤3→1 / else→0
      logic      : ((1.0 * confirmed_edge) + (0.5 * partial_edge)) / (confirmed + partial + misconception 엣지)
                   ratio≥0.7→3 / ratio≥0.4→2 / ratio≥0.2→1 / else→0
      specificity: 노드별 confidence_level 가중 평균 (high=1.0, medium=0.5, low=0.0)
                   ratio≥0.7→3 / ratio≥0.4→2 / ratio≥0.2→1 / else→0
    """
    # ── concept ──
    valid_ref_nodes = [n for n in reference_kg.nodes() if not str(n).startswith("__")]
    total_nodes = len(valid_ref_nodes)
    confirmed = get_nodes_by_status(user_kg, NodeStatus.CONFIRMED)
    partial   = get_nodes_by_status(user_kg, NodeStatus.PARTIAL)
    concept_score = (1.0 * len(confirmed) + 0.5 * len(partial)) / total_nodes if total_nodes > 0 else 0.0
    concept = 3 if concept_score >= 0.7 else 2 if concept_score >= 0.4 else 1 if concept_score >= 0.2 else 0

    # ── accuracy ──
    misconception_nodes = [
        n for n, attrs in user_kg.nodes(data=True)
        if attrs.get("status") == NodeStatus.MISCONCEPTION and not str(n).startswith("__")
    ]
    misc_count = len(misconception_nodes)
    mentioned_node_count = len(confirmed) + len(partial) + misc_count
    if mentioned_node_count == 0:
        accuracy = 0
    else:
        accuracy_score = (1.0 * len(confirmed) + 0.5 * len(partial)) / mentioned_node_count
        if accuracy_score >= 0.7 and misc_count == 0:
            accuracy = 3
        elif accuracy_score >= 0.4 and misc_count <= 1:
            accuracy = 2
        elif accuracy_score >= 0.2 and misc_count <= 3:
            accuracy = 1
        else:
            accuracy = 0

    # ── logic ──
    confirmed_edges     = get_edges_by_status(user_kg, EdgeStatus.CONFIRMED)
    partial_edges       = get_edges_by_status(user_kg, EdgeStatus.PARTIAL)
    misconception_edges = get_edges_by_status(user_kg, EdgeStatus.MISCONCEPTION)
    mentioned_edge_count = len(confirmed_edges) + len(partial_edges) + len(misconception_edges)
    if mentioned_edge_count == 0:
        logic = 0
    else:
        logic_score = (1.0 * len(confirmed_edges) + 0.5 * len(partial_edges)) / mentioned_edge_count
        logic = 3 if logic_score >= 0.7 else 2 if logic_score >= 0.4 else 1 if logic_score >= 0.2 else 0

    # ── specificity ── (노드별 confidence_level 가중 평균)
    all_mentioned = confirmed + partial + misconception_nodes
    if not all_mentioned:
        specificity = 0
    else:
        total_score = sum(
            _CONFIDENCE_SCORE.get(user_kg.nodes[n].get("confidence_level", "low"), 0.0)
            for n in all_mentioned if n in user_kg
        )
        ratio = total_score / len(all_mentioned)
        specificity = 3 if ratio >= 0.7 else 2 if ratio >= 0.4 else 1 if ratio >= 0.2 else 0

    return RubricScores(concept=concept, accuracy=accuracy, logic=logic, specificity=specificity)


# ── confidence_level LLM 평가 ──────────────────────────────

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
    model: str = "gpt-4o-mini",
) -> dict[str, str]:
    """
    언급된 노드별 confidence_level을 별도 LLM 호출로 평가한다.
    """
    if not mentioned_node_ids:
        return {}

    rag_context = "(검색된 학습자료 없음)" if not rag_chunks else "\n\n".join(
        f"[청크 {i+1}]\n{chunk}" for i, chunk in enumerate(rag_chunks)
    )
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
