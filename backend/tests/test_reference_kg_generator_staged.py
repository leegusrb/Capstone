import networkx as nx

from app.services import reference_kg_generator as kg
from app.services.kg_service import serialize_kg


def test_node_candidate_consensus_normalizes_and_filters_rare_nodes():
    runs = [
        [
            kg.NodeCandidate("딥러닝(深層學習)", "딥러닝은 신경망을 기반으로 한다."),
            kg.NodeCandidate("신경망", "신경망은 뉴런 구조를 모방한다."),
        ],
        [
            kg.NodeCandidate("딥러닝", "딥러닝은 여러 층을 사용한다."),
        ],
        [
            kg.NodeCandidate("딥러닝", "딥러닝은 표현 학습에 사용된다."),
            kg.NodeCandidate("희귀 개념", "한 번만 등장한 개념이다."),
        ],
    ]

    assert kg._merge_node_candidate_runs(runs) == ["딥러닝"]


def test_detail_parser_rejects_nodes_and_edges_outside_allowed_set():
    data = {
        "nodes": [
            {
                "id": "A",
                "checklist": [{"item": "A를 명시", "source_quote": "A는 핵심이다."}],
            },
            {
                "id": "B",
                "checklist": [{"item": "B를 명시", "source_quote": "B는 하위 개념이다."}],
            },
            {
                "id": "C",
                "checklist": [{"item": "C를 명시", "source_quote": "C는 목록 밖이다."}],
            },
        ],
        "edges": [
            {"source": "A", "relation": "포함한다", "target": "B"},
            {"source": "A", "relation": "포함한다", "target": "C"},
        ],
    }

    parsed = kg._parse_to_dataclass(data, allowed_node_ids={"A", "B"})

    assert [node.id for node in parsed.nodes] == ["A", "B"]
    assert [(edge.source, edge.relation, edge.target) for edge in parsed.edges] == [
        ("A", "포함한다", "B"),
    ]


def test_serialize_kg_order_is_stable():
    graph = nx.DiGraph()
    graph.add_node("B", status="reference")
    graph.add_node("A", status="reference")
    graph.add_edge("B", "A", relation="포함한다", status="reference")

    assert serialize_kg(graph) == {
        "nodes": [
            {"id": "A", "status": "reference"},
            {"id": "B", "status": "reference"},
        ],
        "edges": [
            {
                "source": "B",
                "target": "A",
                "relation": "포함한다",
                "status": "reference",
            },
        ],
    }


def test_generate_reference_kg_uses_fixed_nodes_for_detail_stage(monkeypatch):
    def fake_node_run(text, model):
        return [
            kg.NodeCandidate("A", "A는 핵심이다."),
            kg.NodeCandidate("B", "B는 하위 개념이다."),
        ]

    def fake_detail_run(text, node_ids, model):
        assert node_ids == ["A", "B"]
        data = {
            "nodes": [
                {
                    "id": "A",
                    "checklist": [{"item": "A를 명시", "source_quote": "A는 핵심이다."}],
                },
                {
                    "id": "B",
                    "checklist": [{"item": "B를 명시", "source_quote": "B는 하위 개념이다."}],
                },
                {
                    "id": "C",
                    "checklist": [{"item": "C를 명시", "source_quote": "C는 목록 밖이다."}],
                },
            ],
            "edges": [
                {"source": "A", "relation": "포함한다", "target": "B"},
                {"source": "A", "relation": "포함한다", "target": "C"},
            ],
        }
        return kg._parse_to_dataclass(data, allowed_node_ids=set(node_ids))

    monkeypatch.setattr(kg, "_generate_node_candidate_run", fake_node_run)
    monkeypatch.setattr(kg, "_generate_detail_run", fake_detail_run)

    graph = kg.generate_reference_kg(
        ["A는 핵심이다.\nB는 하위 개념이다."],
        n_runs=3,
        root_concept="Root",
    )

    assert "A" in graph
    assert "B" in graph
    assert "C" not in graph
    assert graph.has_edge("A", "B")
