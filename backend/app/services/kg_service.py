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

# 동기 OpenAI 클라이언트 (기존 embedding_service와 동일한 방식)
_openai_client = OpenAI(api_key=settings.openai_api_key)


# ──────────────────────────────────────────────
# 1. 상태 정의
# ──────────────────────────────────────────────

class NodeStatus(str, Enum):
    CONFIRMED     = "confirmed"       # 사용자가 정확하게 설명한 개념
    PARTIAL       = "partial"         # 언급됐지만 설명이 불완전한 개념
    MISSING       = "missing"         # 아직 설명되지 않은 개념
    MISCONCEPTION = "misconception"   # 잘못 설명된 오개념


class EdgeStatus(str, Enum):
    CONFIRMED = "confirmed"
    PARTIAL   = "partial"
    MISSING   = "missing"


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

규칙:
1. nodes: 핵심 개념 5~20개를 추출합니다.
2. edges: 두 개념 사이의 관계를 추출합니다. relation에는 짧은 동사구를 사용합니다.
   예시: "포함한다", "의존한다", "구성요소이다", "연결 방식은", "특성은"
3. 너무 세분화되거나 너무 추상적인 개념은 제외합니다.
4. 반드시 아래 JSON 형식만 반환하세요. 설명이나 마크다운 없이 순수 JSON만.

반환 형식:
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
    # 청크를 합쳐서 LLM에 전달 (토큰 절약을 위해 6000자 제한)
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

    # 코드블록으로 감싸진 경우 제거
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

    # NetworkX 그래프 구성
    graph = nx.DiGraph()

    for node_id in data.get("nodes", []):
        graph.add_node(str(node_id), status="reference")

    for edge in data.get("edges", []):
        src = str(edge["source"])
        tgt = str(edge["target"])
        rel = str(edge.get("relation", "관련"))

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
    return graph


# ──────────────────────────────────────────────
# 4. User KG 초기화
# ──────────────────────────────────────────────

def init_user_kg(reference_kg: nx.DiGraph) -> nx.DiGraph:
    """
    Reference KG를 기반으로 User KG를 초기화한다.
    모든 노드/엣지는 missing 상태로 시작.
    """
    user_kg = nx.DiGraph()

    for node_id in reference_kg.nodes():
        user_kg.add_node(node_id, status=NodeStatus.MISSING)

    for src, tgt, attrs in reference_kg.edges(data=True):
        user_kg.add_edge(
            src, tgt,
            relation=attrs.get("relation", "관련"),
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
    """
    Reference KG와 User KG를 DB에 저장한다.
    이미 존재하면 덮어쓴다.
    """
    kg_record = db.query(KnowledgeGraph).filter_by(document_id=document_id).first()

    ref_data  = serialize_kg(reference_kg)
    user_data = serialize_kg(user_kg)

    if kg_record:
        # 이미 있으면 업데이트
        kg_record.reference_kg = ref_data
        kg_record.user_kg      = user_data
    else:
        kg_record = KnowledgeGraph(
            document_id  = document_id,
            reference_kg = ref_data,
            user_kg      = user_data,
        )
        db.add(kg_record)

    db.commit()
    db.refresh(kg_record)
    return kg_record


def load_kg_from_db(db: Session, document_id: int) -> tuple[nx.DiGraph, nx.DiGraph] | None:
    """
    DB에서 KG를 불러와 NetworkX 그래프로 복원한다.

    Returns:
        (reference_kg, user_kg) 튜플.
        레코드가 없으면 None 반환.
    """
    kg_record = db.query(KnowledgeGraph).filter_by(document_id=document_id).first()

    if not kg_record:
        return None

    reference_kg = deserialize_kg(kg_record.reference_kg or {"nodes": [], "edges": []})
    user_kg      = deserialize_kg(kg_record.user_kg      or {"nodes": [], "edges": []})

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
    """
    updated = evaluator_result.get("updated_user_kg", {})

    for node in updated.get("nodes", []):
        node_id = node["id"]
        status  = node.get("status", NodeStatus.MISSING)
        if node_id in user_kg:
            user_kg.nodes[node_id]["status"] = status
        else:
            user_kg.add_node(node_id, status=status)

    for edge in updated.get("edges", []):
        src    = edge["source"]
        tgt    = edge["target"]
        rel    = edge.get("relation", "관련")
        status = edge.get("status", EdgeStatus.MISSING)
        if user_kg.has_edge(src, tgt):
            user_kg[src][tgt]["status"]   = status
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
        "partial_nodes":   get_nodes_by_status(user_kg, NodeStatus.PARTIAL),
        "confirmed_edges": get_edges_by_status(user_kg, EdgeStatus.CONFIRMED),
        "partial_edges":   get_edges_by_status(user_kg, EdgeStatus.PARTIAL),
    }


def get_missing_nodes(user_kg: nx.DiGraph) -> list[str]:
    """세션 종료 시 사용자에게 보여줄 미완료 개념 목록."""
    return get_nodes_by_status(user_kg, NodeStatus.MISSING)


def get_kg_coverage(user_kg: nx.DiGraph, reference_kg: nx.DiGraph) -> dict:
    """
    KG 커버리지 계산.
    커버리지 = confirmed 노드 수 / Reference KG 전체 노드 수 × 100
    """
    total     = reference_kg.number_of_nodes()
    confirmed = len(get_nodes_by_status(user_kg, NodeStatus.CONFIRMED))
    coverage  = round(confirmed / total * 100, 1) if total > 0 else 0.0
    return {
        "confirmed_count":  confirmed,
        "total_count":      total,
        "coverage_percent": coverage,
    }