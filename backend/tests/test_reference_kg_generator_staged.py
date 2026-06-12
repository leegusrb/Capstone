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


def test_parser_rejects_page_marker_nodes():
    candidates = kg._parse_node_candidates({
        "nodes": [
            {"id": "[page_number=1]", "source_quote": "[page_number=1]"},
            {"id": "딥러닝", "source_quote": "딥러닝은 여러 층을 사용한다."},
        ],
    })

    assert [node.id for node in candidates] == ["딥러닝"]

    parsed = kg._parse_to_dataclass({
        "nodes": [
            {
                "id": "[page_number=1]",
                "checklist": [{"item": "페이지를 명시", "source_quote": "[page_number=1]"}],
            },
            {
                "id": "딥러닝",
                "checklist": [{"item": "딥러닝을 명시", "source_quote": "딥러닝은 여러 층을 사용한다."}],
            },
        ],
        "edges": [],
    })

    assert [node.id for node in parsed.nodes] == ["딥러닝"]


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


def test_detail_parser_preserves_checklist_page_number():
    data = {
        "nodes": [
            {
                "id": "A",
                "checklist": [
                    {
                        "item": "A를 명시",
                        "source_quote": "A는 핵심이다.",
                        "page_number": 2,
                    }
                ],
            },
        ],
        "edges": [],
    }

    parsed = kg._parse_to_dataclass(data)

    assert parsed.nodes[0].checklist[0].page_number == 2


def test_detail_parser_normalizes_node_importance():
    data = {
        "nodes": [
            {
                "id": "A",
                "importance": "high",
                "checklist": [{"item": "A를 명시", "source_quote": "A는 핵심이다."}],
            },
            {
                "id": "B",
                "importance": "not-valid",
                "checklist": [{"item": "B를 명시", "source_quote": "B는 하위 개념이다."}],
            },
            {
                "id": "C",
                "checklist": [{"item": "C를 명시", "source_quote": "C는 보조 개념이다."}],
            },
        ],
        "edges": [],
    }

    parsed = kg._parse_to_dataclass(data)

    assert {node.id: node.importance for node in parsed.nodes} == {
        "A": "high",
        "B": "medium",
        "C": "medium",
    }


def test_chunks_are_formatted_with_page_markers():
    chunks = [
        {"content": "A는 핵심이다.", "page_number": 2},
        {"content": "B는 하위 개념이다.", "page_number": 3},
    ]

    text = kg._format_chunks_for_prompt(kg._normalize_source_chunks(chunks))

    assert "[page_number=2]" in text
    assert "[page_number=3]" in text
    assert "A는 핵심이다." in text


def test_root_concept_ignores_page_marker():
    text = "[page_number=1]\n딥러닝 개요\n딥러닝은 여러 층을 사용한다."

    assert kg._extract_root_concept(text) == "딥러닝 개요"


def test_attach_root_connects_existing_root_to_top_nodes():
    graph = nx.DiGraph()
    graph.add_node("Root", status="reference", checklist=[])
    graph.add_node("A", status="reference", checklist=[])

    graph = kg._attach_root_node(graph, "Root")

    assert graph.has_edge("Root", "A")
    assert nx.has_path(graph, "Root", "A")


def test_attach_root_connects_cyclic_component_without_top_node():
    graph = nx.DiGraph()
    graph.add_node("A", status="reference", checklist=[])
    graph.add_node("B", status="reference", checklist=[])
    graph.add_edge("A", "B", relation="포함한다", status="reference")
    graph.add_edge("B", "A", relation="포함한다", status="reference")

    graph = kg._attach_root_node(graph, "Root")

    assert nx.has_path(graph, "Root", "A")
    assert nx.has_path(graph, "Root", "B")


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
