"""
kg_service 단위 테스트
LLM 호출 없이 직렬화, 상태 관리, 비교 연산 검증
"""

import json
from app.services.kg_service import (
    NodeStatus, EdgeStatus,
    serialize_kg, deserialize_kg,
    create_empty_user_kg,
    sync_user_kg_with_reference,
    update_user_kg_from_evaluator,
    get_partial_nodes_and_edges,
    get_missing_nodes,
    get_kg_coverage,
    get_misconceptions,
)
import networkx as nx


# ──────────────────────────────────────────────
# 픽스처: TCP/IP 예시 Reference KG
# ──────────────────────────────────────────────

def make_reference_kg() -> nx.DiGraph:
    g = nx.DiGraph()
    nodes = ["TCP", "연결 지향", "3-way handshake", "흐름 제어", "혼잡 제어", "ACK"]
    for n in nodes:
        g.add_node(n, status="reference")
    edges = [
        ("TCP", "연결 지향",     "특성"),
        ("TCP", "3-way handshake", "연결 방식"),
        ("TCP", "흐름 제어",     "포함"),
        ("TCP", "혼잡 제어",     "포함"),
        ("TCP", "ACK",           "사용"),
    ]
    for src, tgt, rel in edges:
        g.add_edge(src, tgt, relation=rel, status="reference")
    return g


# ──────────────────────────────────────────────
# 테스트 1 — 직렬화 / 역직렬화 왕복
# ──────────────────────────────────────────────

def test_serialize_roundtrip():
    ref_kg = make_reference_kg()
    data   = serialize_kg(ref_kg)
    restored = deserialize_kg(data)

    assert set(ref_kg.nodes()) == set(restored.nodes()), "노드 불일치"
    assert set(ref_kg.edges()) == set(restored.edges()), "엣지 불일치"

    # 노드 속성 보존 확인
    for node_id in ref_kg.nodes():
        assert ref_kg.nodes[node_id]["status"] == restored.nodes[node_id]["status"]

    print("✅ test_serialize_roundtrip 통과")


# ──────────────────────────────────────────────
# 테스트 2 — User KG 동기화 (missing 채우기)
# ──────────────────────────────────────────────

def test_sync_user_kg():
    ref_kg  = make_reference_kg()
    user_kg = create_empty_user_kg()
    user_kg = sync_user_kg_with_reference(user_kg, ref_kg)

    missing = get_missing_nodes(user_kg)
    assert set(missing) == {"TCP", "연결 지향", "3-way handshake", "흐름 제어", "혼잡 제어", "ACK"}

    print("✅ test_sync_user_kg 통과 — missing 노드:", missing)


# ──────────────────────────────────────────────
# 테스트 3 — Evaluator 결과 반영
# ──────────────────────────────────────────────

def test_update_user_kg():
    ref_kg  = make_reference_kg()
    user_kg = create_empty_user_kg()
    user_kg = sync_user_kg_with_reference(user_kg, ref_kg)

    # Evaluator가 반환한 결과 (사용자가 TCP, 연결 지향, 흐름 제어를 설명함)
    evaluator_result = {
        "updated_user_kg": {
            "nodes": [
                {"id": "TCP",      "status": "confirmed"},
                {"id": "연결 지향", "status": "confirmed"},
                {"id": "흐름 제어", "status": "partial"},
            ],
            "edges": [
                {"source": "TCP", "relation": "특성",  "target": "연결 지향", "status": "confirmed"},
                {"source": "TCP", "relation": "포함",  "target": "흐름 제어", "status": "partial"},
            ],
        },
        "misconceptions": [],
    }

    user_kg = update_user_kg_from_evaluator(user_kg, evaluator_result)

    # 상태 확인
    assert user_kg.nodes["TCP"]["status"]      == "confirmed"
    assert user_kg.nodes["연결 지향"]["status"] == "confirmed"
    assert user_kg.nodes["흐름 제어"]["status"] == "partial"
    assert user_kg.nodes["혼잡 제어"]["status"] == NodeStatus.MISSING
    assert user_kg.nodes["ACK"]["status"]       == NodeStatus.MISSING

    print("✅ test_update_user_kg 통과")


# ──────────────────────────────────────────────
# 테스트 4 — partial 추출 (Student LLM용)
# ──────────────────────────────────────────────

def test_get_partial_for_student():
    ref_kg  = make_reference_kg()
    user_kg = create_empty_user_kg()
    user_kg = sync_user_kg_with_reference(user_kg, ref_kg)

    evaluator_result = {
        "updated_user_kg": {
            "nodes": [
                {"id": "TCP",      "status": "confirmed"},
                {"id": "흐름 제어", "status": "partial"},
            ],
            "edges": [
                {"source": "TCP", "relation": "포함", "target": "흐름 제어", "status": "partial"},
            ],
        },
        "misconceptions": [],
    }
    user_kg = update_user_kg_from_evaluator(user_kg, evaluator_result)

    student_context = get_partial_nodes_and_edges(user_kg)

    # missing 노드가 절대 포함되지 않아야 함
    all_nodes = student_context["confirmed_nodes"] + student_context["partial_nodes"]
    assert "혼잡 제어"    not in all_nodes, "missing 노드가 Student LLM에 노출됨!"
    assert "3-way handshake" not in all_nodes, "missing 노드가 Student LLM에 노출됨!"
    assert "ACK"          not in all_nodes, "missing 노드가 Student LLM에 노출됨!"

    assert "TCP"      in student_context["confirmed_nodes"]
    assert "흐름 제어" in student_context["partial_nodes"]

    print("✅ test_get_partial_for_student 통과")
    print("   Student LLM 전달 컨텍스트:", json.dumps(student_context, ensure_ascii=False, indent=2))


# ──────────────────────────────────────────────
# 테스트 5 — KG 커버리지 계산
# ──────────────────────────────────────────────

def test_kg_coverage():
    ref_kg  = make_reference_kg()
    user_kg = create_empty_user_kg()
    user_kg = sync_user_kg_with_reference(user_kg, ref_kg)

    evaluator_result = {
        "updated_user_kg": {
            "nodes": [
                {"id": "TCP",            "status": "confirmed"},
                {"id": "연결 지향",       "status": "confirmed"},
                {"id": "3-way handshake", "status": "confirmed"},
            ],
            "edges": [],
        },
        "misconceptions": [],
    }
    user_kg = update_user_kg_from_evaluator(user_kg, evaluator_result)

    coverage = get_kg_coverage(user_kg, ref_kg)
    # 6개 중 3개 confirmed → 50%
    assert coverage["confirmed_count"]  == 3
    assert coverage["total_count"]      == 6
    assert coverage["coverage_percent"] == 50.0

    print("✅ test_kg_coverage 통과 — 커버리지:", coverage)


# ──────────────────────────────────────────────
# 테스트 6 — 오개념 기록
# ──────────────────────────────────────────────

def test_misconceptions():
    user_kg = create_empty_user_kg()
    evaluator_result = {
        "updated_user_kg": {"nodes": [], "edges": []},
        "misconceptions": [
            {"content": "TCP는 비연결형 프로토콜이다", "correction": "TCP는 연결 지향 프로토콜이다"},
        ],
    }
    user_kg = update_user_kg_from_evaluator(user_kg, evaluator_result)

    misc = get_misconceptions(user_kg)
    assert len(misc) == 1
    assert misc[0]["content"] == "TCP는 비연결형 프로토콜이다"

    print("✅ test_misconceptions 통과 — 오개념:", misc)


# ──────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────

if __name__ == "__main__":
    test_serialize_roundtrip()
    test_sync_user_kg()
    test_update_user_kg()
    test_get_partial_for_student()
    test_kg_coverage()
    test_misconceptions()
    print("\n🎉 모든 테스트 통과")