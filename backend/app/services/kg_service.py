"""
services/kg_service.py
----------------------
Knowledge Graph 생성 및 관리 서비스.

주요 역할:
  1. Reference KG 생성  — PDF 청크 텍스트 → LLM → NetworkX → JSON 직렬화
  2. User KG 초기화     — Reference KG의 모든 노드/엣지를 missing 상태로 복사
  3. KG 비교 / 상태관리 — confirmed / partial / missing / misconception 전이
  4. 조회 헬퍼          — Student LLM용 partial 추출, 커버리지 계산 등
  5. DB 저장/불러오기   — KnowledgeGraph 모델과 연동

[변경 이력]
  - RelationType Enum 추가: LLM이 생성하는 relation을 고정 타입셋으로 제한
  - EdgeStatus.MISCONCEPTION 추가: 방향 역전·잘못된 관계 타입 감지 가능
  - _EXTRACTION_PROMPT 업데이트: 허용 relation 목록 명시`
"""

import json
import logging
from enum import Enum

import networkx as nx
from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.models.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=settings.openai_api_key)


# ──────────────────────────────────────────────
# 1. 상태 및 타입 정의
# ──────────────────────────────────────────────

class NodeStatus(str, Enum):
    CONFIRMED = "confirmed"  # 사용자가 정확하게 설명한 개념
    PARTIAL = "partial"  # 언급됐지만 설명이 불완전한 개념
    MISSING = "missing"  # 아직 설명되지 않은 개념
    MISCONCEPTION = "misconception"  # 잘못 설명된 오개념


class EdgeStatus(str, Enum):
    CONFIRMED = "confirmed"  # 관계를 정확하게 설명함
    PARTIAL = "partial"  # 관계를 언급했지만 설명이 불완전함
    MISSING = "missing"  # 관계를 아직 설명하지 않음
    MISCONCEPTION = "misconception"  # 관계 방향 역전 또는 잘못된 타입으로 설명함


class RelationType(str, Enum):
    """
    KG에서 허용되는 엣지 relation 고정 타입셋.

    LLM이 relation을 자유롭게 생성하면 같은 관계가 다른 표현으로 나타나
    Evaluator LLM의 비교 정확도가 떨어진다. 이를 방지하기 위해 9개 타입으로 고정한다.

    선택 기준:
      - 학습 자료 도메인에 무관하게 범용적으로 적용 가능한 관계만 포함
      - 7~10개 수준 유지 (너무 세밀하면 LLM이 엉뚱한 타입을 고르는 오류 증가)
    """
    # 구조적 관계
    CONTAINS = "포함한다"  # A가 B를 내부 구성으로 포함  (TCP → 흐름 제어)
    IS_PART_OF = "구성요소이다"  # A가 B의 부분/구성요소       (슬라이딩 윈도우 → 흐름 제어)
    IS_TYPE_OF = "종류이다"  # A가 B의 한 유형/종류        (TCP → 전송 계층 프로토콜)

    # 기능적 관계
    USES = "사용한다"  # A가 B를 수단/방법으로 활용   (흐름 제어 → 슬라이딩 윈도우)
    REQUIRES = "전제한다"  # A가 동작하려면 B가 필요      (혼잡 제어 → ACK)
    ENABLES = "가능하게 한다"  # A로 인해 B가 달성됨         (3-way handshake → 연결 수립)
    CAUSES = "야기한다"  # A가 B를 발생시킴            (혼잡 → 패킷 손실)

    # 설명적 관계
    HAS_PROPERTY = "특성을 가진다"  # A가 B라는 속성을 가짐       (TCP → 연결 지향)
    IS_EXAMPLE_OF = "예시이다"  # A가 B의 구체적 예시         (슬라이딩 윈도우 → 흐름 제어 메커니즘)


# 프롬프트 삽입용 — 각 타입의 의미 설명 포함
_RELATION_TYPE_GUIDE = """\
사용 가능한 relation 목록 (반드시 이 중 하나만 사용할 것):
┌──────────────────┬────────────────────────────────────────────────────┐
│ relation 값       │ 사용 조건                                           │
├──────────────────┼────────────────────────────────────────────────────┤
│ "포함한다"         │ A가 B를 내부 구성으로 포함하는 경우                    │
│ "구성요소이다"     │ A가 B의 부분 또는 구성요소인 경우                      │
│ "종류이다"         │ A가 B의 한 종류 또는 유형인 경우                       │
│ "사용한다"         │ A가 B를 수단 또는 방법으로 활용하는 경우                │
│ "전제한다"         │ A가 동작하려면 B가 먼저 필요한 경우                    │
│ "가능하게 한다"    │ A로 인해 B가 수행되거나 달성되는 경우                   │
│ "야기한다"         │ A가 B를 발생시키거나 원인이 되는 경우                   │
│ "특성을 가진다"    │ A가 B라는 속성 또는 특징을 가지는 경우                  │
│ "예시이다"         │ A가 B의 구체적 예시인 경우                             │
└──────────────────┴────────────────────────────────────────────────────┘
위 9개 외의 표현은 절대 사용하지 마세요."""

# RelationType 허용값 집합 (검증용)
_ALLOWED_RELATIONS: set[str] = {rt.value for rt in RelationType}


# ──────────────────────────────────────────────
# 2. 직렬화 / 역직렬화
# ──────────────────────────────────────────────

def serialize_kg(graph: nx.DiGraph) -> dict:
    """NetworkX DiGraph → JSON 저장 가능한 dict 변환. 모든 노드/엣지 속성 보존."""
    nodes = []
    for node_id, attrs in graph.nodes(data=True):
        nodes.append({"id": node_id, **attrs})

    edges = []
    for src, tgt, attrs in graph.edges(data=True):
        edges.append({"source": src, "target": tgt, **attrs})

    return {"nodes": nodes, "edges": edges}


def deserialize_kg(data: dict) -> nx.DiGraph:
    """dict → NetworkX DiGraph 복원. DB에서 불러올 때 사용."""
    graph = nx.DiGraph()

    for node in data.get("nodes", []):
        node_copy = dict(node)
        node_id = node_copy.pop("id")
        graph.add_node(node_id, **node_copy)

    for edge in data.get("edges", []):
        edge_copy = dict(edge)
        src = edge_copy.pop("source")
        tgt = edge_copy.pop("target")
        graph.add_edge(src, tgt, **edge_copy)

    return graph


# ──────────────────────────────────────────────
# 3. Reference KG 생성 (LLM 호출)
# ──────────────────────────────────────────────

_EXTRACTION_PROMPT = """\
당신은 학습 자료에서 핵심 개념과 개념 간 관계를 추출하는 전문가입니다.

아래 학습 자료 텍스트를 분석해서 지식 그래프 형태로 정리해주세요.

━━━ 노드 추출 규칙 ━━━
1. [단일 개념 원칙] 하나의 노드는 반드시 하나의 단일 개념 또는 용어만 나타냅니다.
   - 복합 개념(예: "흐름 제어와 혼잡 제어")은 반드시 별도 노드로 분리하세요.
   - 잘못된 예: 노드 = "흐름 제어와 혼잡 제어"
   - 올바른 예: 노드 = "흐름 제어", 노드 = "혼잡 제어"

2. [하위 메커니즘 분리] 특정 개념의 구현 방식·구성 요소·하위 메커니즘이
   독립적으로 설명 가능한 경우 별도 노드로 추출합니다.
   - 예: "흐름 제어" → 하위에 "슬라이딩 윈도우", "버퍼"를 별도 노드로 분리

3. [과도한 세분화 금지] 자료에서 핵심 역할을 하지 않는 지나치게 세부적인 용어는
   상위 개념 노드에 포함합니다. 전체 노드 수는 5~20개를 목표로 합니다.

━━━ 엣지 추출 규칙 ━━━
4. [고정 relation 타입 사용] relation은 반드시 아래 9개 중 하나만 사용합니다.
   임의의 동사구를 만들지 마세요.

""" + _RELATION_TYPE_GUIDE + """

5. [방향성 명시] 모든 엣지는 source → target 방향을 명확히 지정합니다.
   - 올바른 예: TCP(source) -[포함한다]-> 흐름 제어(target)
   - 잘못된 예: 흐름 제어(source) -[포함한다]-> TCP(target)  ← 방향 역전

━━━ 출력 형식 ━━━
반드시 아래 JSON 형식만 반환하세요. 설명이나 마크다운 없이 순수 JSON만.

{
  "nodes": ["개념1", "개념2"],
  "edges": [
    {"source": "개념1", "relation": "포함한다", "target": "개념2"}
  ]
}

학습 자료:
"""


def build_reference_kg(text_chunks: list[str], model: str = "gpt-4o-mini") -> nx.DiGraph:
    """
    PDF 청크 텍스트 리스트 → LLM → Reference KG 생성.
    문서 업로드 시 1회만 실행.

    Args:
        text_chunks : pdf_service.extract_and_chunk_pdf()에서 추출한 텍스트 청크 목록
        model       : 사용할 OpenAI 모델 (기본값: gpt-4o-mini)

    Returns:
        Reference KG (nx.DiGraph). 모든 노드 status = "reference".
    """
    combined = "\n\n".join(text_chunks)
    if len(combined) > 6000:
        combined = combined[:6000] + "\n...(이하 생략)"

    logger.info("Reference KG 추출 시작 (텍스트 %d자)", len(combined))

    response = _openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _EXTRACTION_PROMPT + combined}],
        temperature=0.1,
    )

    raw = response.choices[0].message.content.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Reference KG JSON 파싱 실패: %s\n원본: %s", e, raw)
        raise ValueError(f"LLM이 올바른 JSON을 반환하지 않았습니다: {e}") from e

    graph = nx.DiGraph()

    for node_id in data.get("nodes", []):
        graph.add_node(str(node_id), status="reference")

    invalid_relations_found = []

    for edge in data.get("edges", []):
        src = str(edge["source"])
        tgt = str(edge["target"])
        rel = str(edge.get("relation", "포함한다"))

        # ── relation 타입 검증 ──────────────────────────────
        # 허용된 9개 타입 외의 표현이 나오면 경고 후 가장 유사한 타입으로 fallback
        if rel not in _ALLOWED_RELATIONS:
            logger.warning(
                "허용되지 않은 relation 감지: '%s' -[%s]-> '%s'. "
                "프롬프트 규칙 위반 — '포함한다'로 fallback 처리합니다.",
                src, rel, tgt,
            )
            invalid_relations_found.append((src, rel, tgt))
            rel = RelationType.CONTAINS.value  # 가장 범용적인 타입으로 fallback

        if src not in graph:
            graph.add_node(src, status="reference")
        if tgt not in graph:
            graph.add_node(tgt, status="reference")

        graph.add_edge(src, tgt, relation=rel, status="reference")

    logger.info(
        "Reference KG 생성 완료 — 노드 %d개, 엣지 %d개",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )

    if invalid_relations_found:
        logger.warning(
            "비허용 relation %d개 발견 (fallback 처리됨): %s",
            len(invalid_relations_found),
            invalid_relations_found,
        )
    else:
        logger.info("KG 품질 검증 통과 — 모든 relation이 허용 타입셋 내에 있음.")

    return graph


# ──────────────────────────────────────────────
# 4. User KG 초기화
# ──────────────────────────────────────────────

def init_user_kg(reference_kg: nx.DiGraph) -> nx.DiGraph:
    """
    Reference KG를 기반으로 User KG를 초기화한다.
    모든 노드/엣지는 missing 상태로 시작.
    relation은 Reference KG에서 그대로 복사 (RelationType 보장됨).
    """
    user_kg = nx.DiGraph()

    for node_id in reference_kg.nodes():
        user_kg.add_node(node_id, status=NodeStatus.MISSING)

    for src, tgt, attrs in reference_kg.edges(data=True):
        user_kg.add_edge(
            src, tgt,
            relation=attrs.get("relation", RelationType.CONTAINS.value),
            status=EdgeStatus.MISSING,
        )

    return user_kg


# ──────────────────────────────────────────────
# 5. DB 저장 / 불러오기
# ──────────────────────────────────────────────

def save_kg_to_db(
        db: Session,
        document_id: int,
        reference_kg: nx.DiGraph,
        user_kg: nx.DiGraph,
) -> KnowledgeGraph:
    """Reference KG와 User KG를 DB에 저장한다. 이미 존재하면 덮어쓴다."""
    kg_record = db.query(KnowledgeGraph).filter_by(document_id=document_id).first()

    ref_data = serialize_kg(reference_kg)
    user_data = serialize_kg(user_kg)

    if kg_record:
        kg_record.reference_kg = ref_data
        kg_record.user_kg = user_data
    else:
        kg_record = KnowledgeGraph(
            document_id=document_id,
            reference_kg=ref_data,
            user_kg=user_data,
        )
        db.add(kg_record)

    db.commit()
    db.refresh(kg_record)
    return kg_record


def load_kg_from_db(db: Session, document_id: int) -> tuple[nx.DiGraph, nx.DiGraph] | None:
    """
    DB에서 KG를 불러와 NetworkX 그래프로 복원한다.

    Returns:
        (reference_kg, user_kg) 튜플. 레코드가 없으면 None 반환.
    """
    kg_record = db.query(KnowledgeGraph).filter_by(document_id=document_id).first()

    if not kg_record:
        return None

    reference_kg = deserialize_kg(kg_record.reference_kg or {"nodes": [], "edges": []})
    user_kg = deserialize_kg(kg_record.user_kg or {"nodes": [], "edges": []})

    return reference_kg, user_kg


# ──────────────────────────────────────────────
# 6. User KG 업데이트 (Evaluator LLM 결과 반영)
# ──────────────────────────────────────────────

def update_user_kg_from_evaluator(
        user_kg: nx.DiGraph,
        evaluator_result: dict,
) -> nx.DiGraph:
    """
    Evaluator LLM이 반환한 JSON 결과를 User KG에 반영한다.

    evaluator_result 필드:
      - updated_user_kg.nodes : [{"id": "TCP", "status": "confirmed"}, ...]
      - updated_user_kg.edges : [{"source": ..., "relation": ..., "target": ..., "status": ...}]
      - misconceptions        : [{"content": "...", "correction": "..."}]

    엣지 status = "misconception" 처리:
      - 관계 방향 역전 또는 잘못된 relation 타입으로 설명한 경우
      - User KG에 misconception 상태로 기록하되, Reference KG의 올바른 방향은 유지
    """
    updated = evaluator_result.get("updated_user_kg", {})

    for node in updated.get("nodes", []):
        node_id = node["id"]
        status = node.get("status", NodeStatus.MISSING)
        if node_id in user_kg:
            user_kg.nodes[node_id]["status"] = status
        else:
            user_kg.add_node(node_id, status=status)

    for edge in updated.get("edges", []):
        src = edge["source"]
        tgt = edge["target"]
        rel = edge.get("relation", RelationType.CONTAINS.value)
        status = edge.get("status", EdgeStatus.MISSING)

        # relation 타입 검증 — Evaluator LLM도 허용 타입셋 준수 확인
        if rel not in _ALLOWED_RELATIONS:
            logger.warning(
                "Evaluator LLM이 비허용 relation 반환: '%s' -[%s]-> '%s'. fallback 처리.",
                src, rel, tgt,
            )
            rel = RelationType.CONTAINS.value

        if user_kg.has_edge(src, tgt):
            user_kg[src][tgt]["status"] = status
            user_kg[src][tgt]["relation"] = rel
        else:
            if src not in user_kg:
                user_kg.add_node(src, status=NodeStatus.CONFIRMED)
            if tgt not in user_kg:
                user_kg.add_node(tgt, status=NodeStatus.CONFIRMED)
            user_kg.add_edge(src, tgt, relation=rel, status=status)

    # 오개념 기록
    for misc in evaluator_result.get("misconceptions", []):
        misc_node = "__misconceptions__"
        if misc_node not in user_kg:
            user_kg.add_node(misc_node, status=NodeStatus.MISCONCEPTION, items=[])
        user_kg.nodes[misc_node]["items"].append(misc)

    return user_kg


# ──────────────────────────────────────────────
# 7. 조회 헬퍼
# ──────────────────────────────────────────────

def get_nodes_by_status(user_kg: nx.DiGraph, status: NodeStatus) -> list[str]:
    return [
        n for n, attrs in user_kg.nodes(data=True)
        if attrs.get("status") == status and n != "__misconceptions__"
    ]


def get_edges_by_status(user_kg: nx.DiGraph, status: EdgeStatus) -> list[dict]:
    return [
        {"source": src, "relation": attrs.get("relation", ""), "target": tgt}
        for src, tgt, attrs in user_kg.edges(data=True)
        if attrs.get("status") == status
    ]


def get_student_context(user_kg: nx.DiGraph) -> dict:
    """
    Student LLM에 전달할 컨텍스트 추출.
    confirmed + partial 노드/엣지만 포함. missing은 절대 포함 안 됨.
    """
    return {
        "confirmed_nodes": get_nodes_by_status(user_kg, NodeStatus.CONFIRMED),
        "partial_nodes": get_nodes_by_status(user_kg, NodeStatus.PARTIAL),
        "confirmed_edges": get_edges_by_status(user_kg, EdgeStatus.CONFIRMED),
        "partial_edges": get_edges_by_status(user_kg, EdgeStatus.PARTIAL),
    }


def get_missing_nodes(user_kg: nx.DiGraph) -> list[str]:
    """세션 종료 시 사용자에게 보여줄 미완료 개념 목록."""
    return get_nodes_by_status(user_kg, NodeStatus.MISSING)


def get_misconceptions(user_kg: nx.DiGraph) -> list[dict]:
    """기록된 오개념 목록 반환."""
    misc_node = "__misconceptions__"
    if misc_node not in user_kg:
        return []
    return user_kg.nodes[misc_node].get("items", [])


def get_kg_coverage(user_kg: nx.DiGraph, reference_kg: nx.DiGraph) -> dict:
    """
    KG 커버리지 계산.
    커버리지 = confirmed 노드 수 / Reference KG 전체 노드 수 × 100
    """
    total = reference_kg.number_of_nodes()
    confirmed = len(get_nodes_by_status(user_kg, NodeStatus.CONFIRMED))
    coverage = round(confirmed / total * 100, 1) if total > 0 else 0.0
    return {
        "confirmed_count": confirmed,
        "total_count": total,
        "coverage_percent": coverage,
    }
