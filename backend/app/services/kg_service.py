"""
services/kg_service.py
----------------------
Knowledge Graph 관리 서비스.

주요 역할:
  1. User KG 초기화     — Reference KG의 모든 노드/엣지를 missing 상태로 복사
                          (노드별 체크리스트는 Evaluator 전용으로 동거 보존)
  2. KG 비교 / 상태관리 — confirmed / partial / missing / misconception 전이
  3. 조회 헬퍼          — Student LLM용 partial 추출, 커버리지 계산 등
  4. DB 저장/불러오기   — KnowledgeGraph 모델과 연동
  5. 사용자 노출 변환   — 세션 종료 후 노드별 진행도(체크리스트 항목 미노출)

Reference KG 생성은 services/reference_kg_generator.py 가 담당한다.

[변경 이력]
  - RelationType Enum 추가: LLM이 생성하는 relation을 고정 타입셋으로 제한
  - EdgeStatus.MISCONCEPTION 추가: 방향 역전·잘못된 관계 타입 감지 가능
  - build_reference_kg / _EXTRACTION_PROMPT 제거
    → reference_kg_generator.generate_reference_kg() 로 통합
  - init_user_kg / update_user_kg_from_evaluator: 체크리스트 정보 처리 추가
  - get_user_kg_view_for_session_summary 신설 (사용자 노출 가공)
"""

import logging
from enum import Enum

import networkx as nx
from sqlalchemy.orm import Session

from app.models.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


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
# 3. User KG 초기화
# ──────────────────────────────────────────────

def init_user_kg(reference_kg: nx.DiGraph) -> nx.DiGraph:
    """
    Reference KG를 기반으로 User KG를 초기화한다.
    모든 노드/엣지는 missing 상태로 시작.

    노드별 체크리스트(`checklist`)는 Reference KG에서 그대로 복사한다.
    Evaluator LLM 전용 정보로, Student LLM 컨텍스트나 사용자 응답에는 노출되지 않는다
    (PDF §4-1, §5-3 참고).

    추가 필드:
      - checklist_result : 매 턴 Evaluator가 갱신하는 [{"item", "met"}] 배열
      - completion_ratio : met 항목 수 ÷ 전체 항목 수
    """
    user_kg = nx.DiGraph()

    for node_id, attrs in reference_kg.nodes(data=True):
        user_kg.add_node(
            node_id,
            status=NodeStatus.MISSING,
            checklist=attrs.get("checklist", []),
            checklist_result=[],
            completion_ratio=0.0,
        )

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

    evaluator_result.updated_user_kg.nodes 형식 (PDF §6-3):
      {
        "id": "TCP",
        "status": "confirmed|partial|missing|misconception",
        "checklist_result": [{"item": "...", "met": true/false}, ...],
        "completion_ratio": 0.0~1.0
      }

    노드 상태(status)는 PDF §6 표에 따라 Evaluator가 이미 판정한 값을 그대로 신뢰한다.
    체크리스트 항목 met 여부 ↔ 노드 상태의 정합성 검증은 Evaluator의 권한이며,
    여기서는 단순 저장만 수행한다.
    """
    updated = evaluator_result.get("updated_user_kg", {})

    for node in updated.get("nodes", []):
        node_id = node["id"]
        status = node.get("status", NodeStatus.MISSING)
        checklist_result = node.get("checklist_result", [])
        completion_ratio = float(node.get("completion_ratio", 0.0))

        if node_id in user_kg:
            # checklist 병합: met=true는 누적 유지 (한 번 확인된 항목은 되돌리지 않음)
            existing_cl = user_kg.nodes[node_id].get("checklist_result", [])
            if existing_cl and checklist_result:
                existing_met = {item["item"]: item.get("met", False) for item in existing_cl}
                checklist_result = [
                    {"item": item["item"], "met": item.get("met", False) or existing_met.get(item["item"], False)}
                    for item in checklist_result
                ]
            # 병합된 checklist 기반으로 completion_ratio 재계산
            if checklist_result:
                met_count = sum(1 for item in checklist_result if item.get("met", False))
                completion_ratio = met_count / len(checklist_result)

            # status 결정: misconception은 그대로 / 나머지는 병합 ratio 기준
            if status != NodeStatus.MISCONCEPTION:
                status = NodeStatus.CONFIRMED if completion_ratio >= 1.0 else NodeStatus.PARTIAL

            user_kg.nodes[node_id]["status"] = status
            user_kg.nodes[node_id]["checklist_result"] = checklist_result
            user_kg.nodes[node_id]["completion_ratio"] = completion_ratio
            logger.info("KG 업데이트 성공: '%s' → %s (ratio=%.2f)", node_id, status, completion_ratio)
            continue

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
        elif src in user_kg and tgt in user_kg:
            # Reference KG에 없던 엣지지만 양 끝 노드는 존재 → misconception 기록 가능
            user_kg.add_edge(src, tgt, relation=rel, status=status)
        else:
            # 평가 범위 밖 노드를 끝점으로 가진 엣지는 무시
            logger.debug(
                "Evaluator가 Reference KG 외 엣지 반환: %s -[%s]-> %s — User KG 미반영",
                src, rel, tgt,
            )

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


_BEST_SCORES_NODE = "__best_scores__"
_SCORE_KEYS = ("concept", "accuracy", "logic", "specificity")


def get_best_scores(user_kg: nx.DiGraph) -> dict:
    """이전 세션까지 document에서 달성한 카테고리별 최고 점수를 반환한다."""
    if _BEST_SCORES_NODE in user_kg:
        return dict(user_kg.nodes[_BEST_SCORES_NODE].get("scores", {}))
    return {k: 0 for k in _SCORE_KEYS}


def update_best_scores(user_kg: nx.DiGraph, new_scores: dict) -> None:
    """카테고리별 최고 점수를 갱신한다. User KG에 저장되므로 DB에 자동 persist된다."""
    if _BEST_SCORES_NODE not in user_kg:
        user_kg.add_node(_BEST_SCORES_NODE, scores={k: 0 for k in _SCORE_KEYS})
    existing = user_kg.nodes[_BEST_SCORES_NODE].get("scores", {})
    user_kg.nodes[_BEST_SCORES_NODE]["scores"] = {
        k: max(new_scores.get(k, 0), existing.get(k, 0))
        for k in _SCORE_KEYS
    }


_SPECIFICITY_NODE = "__specificity__"
_SPECIFICITY_KEYS = ("example_present", "concrete_terms", "sentence_explained", "context_applied")


def get_specificity_state(user_kg: nx.DiGraph) -> dict:
    """누적된 구체성 체크리스트 상태를 반환한다."""
    if _SPECIFICITY_NODE in user_kg:
        return dict(user_kg.nodes[_SPECIFICITY_NODE].get("checklist", {}))
    return {k: False for k in _SPECIFICITY_KEYS}


def update_specificity_state(user_kg: nx.DiGraph, new_checklist: dict) -> None:
    """구체성 체크리스트를 누적 업데이트한다. true는 한 번 달성되면 유지된다."""
    if _SPECIFICITY_NODE not in user_kg:
        user_kg.add_node(_SPECIFICITY_NODE, checklist={k: False for k in _SPECIFICITY_KEYS})
    existing = user_kg.nodes[_SPECIFICITY_NODE].get("checklist", {})
    user_kg.nodes[_SPECIFICITY_NODE]["checklist"] = {
        k: new_checklist.get(k, False) or existing.get(k, False)
        for k in _SPECIFICITY_KEYS
    }


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


# ──────────────────────────────────────────────
# 8. 사용자 노출 변환 (세션 종료 후 리포트용)
# ──────────────────────────────────────────────
#
# 노출 정책 (세션 진행 중에는 KG 자체를 사용자에게 보여주지 않음):
#   - Reference KG 응답: 체크리스트 정보 전체 제거 (정답 기준 노출 방지)
#   - User KG 응답    : checklist_result(항목 텍스트 + met/unmet) 노출,
#                       Reference에서 복사된 원본 checklist와 source_quote는 제거.
#                       세션 종료 후 사용자가 어느 항목을 빠뜨렸는지 직접 확인 가능.

def get_user_kg_view_for_session_summary(user_kg: nx.DiGraph) -> list[dict]:
    """
    세션 종료 후 사용자에게 보여줄 노드별 진행도 요약.

    각 노드의 체크리스트 전체 항목 + met/unmet 결과를 함께 노출한다.
    source_quote(학습자료 원문 인용)는 제거.
    """
    view = []
    for node_id, attrs in user_kg.nodes(data=True):
        if str(node_id).startswith("__"):
            continue

        original_checklist = attrs.get("checklist", [])
        evaluator_result   = attrs.get("checklist_result", [])

        met_by_item = {
            r.get("item"): bool(r.get("met"))
            for r in evaluator_result
        }

        merged = [
            {
                "item": ck.get("item", ""),
                "met":  met_by_item.get(ck.get("item", ""), False),
            }
            for ck in original_checklist
        ]

        view.append({
            "id":               node_id,
            "status":           attrs.get("status", NodeStatus.MISSING),
            "checklist":        merged,
            "met_count":        sum(1 for ck in merged if ck["met"]),
            "total_count":      len(merged),
            "completion_ratio": float(attrs.get("completion_ratio", 0.0)),
        })
    return view


def strip_checklist_for_reference_view(kg_dict: dict) -> dict:
    """
    Reference KG dict에서 모든 체크리스트 정보를 제거한다.
    정답 기준이 노출되면 학습 효과가 훼손되므로 GET /reference 응답 직전에 사용.
    """
    safe_nodes = [
        {k: v for k, v in node.items() if k not in {"checklist", "checklist_result"}}
        for node in kg_dict.get("nodes", [])
        if not str(node.get("id", "")).startswith("__")
    ]
    return {"nodes": safe_nodes, "edges": kg_dict.get("edges", [])}


def strip_checklist_for_user_view(kg_dict: dict) -> dict:
    """
    User KG dict를 사용자 노출용으로 가공한다 (세션 종료 후 노출).

    각 노드의 체크리스트 전체 항목 + 평가 결과(met/unmet)를 함께 노출한다.
    프론트에서 "어느 항목을 잘 설명했고, 어느 항목이 남았는지"를
    시각화할 수 있도록 한다.

    제거 : source_quote (학습자료 원문 인용 — 정답 누출 방지)
    노출 : checklist[*].{item, met}  ← Reference 원본 항목 + 평가 결과 머지
    추가 : met_count / total_count
    """
    safe_nodes = []
    for node in kg_dict.get("nodes", []):
        if str(node.get("id", "")).startswith("__"):
            continue
        original_checklist = node.get("checklist", [])          # [{item, source_quote}, ...]
        evaluator_result   = node.get("checklist_result", [])   # [{item, met}, ...]

        met_by_item = {
            r.get("item"): bool(r.get("met"))
            for r in evaluator_result
        }

        merged = [
            {
                "item": ck.get("item", ""),
                "met":  met_by_item.get(ck.get("item", ""), False),
            }
            for ck in original_checklist
        ]

        safe = {
            k: v for k, v in node.items()
            if k not in {"checklist", "checklist_result"}
        }
        safe["checklist"]   = merged
        safe["met_count"]   = sum(1 for ck in merged if ck["met"])
        safe["total_count"] = len(merged)
        safe_nodes.append(safe)

    return {"nodes": safe_nodes, "edges": kg_dict.get("edges", [])}
