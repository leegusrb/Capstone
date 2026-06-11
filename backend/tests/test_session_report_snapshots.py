import os
from datetime import datetime
from types import SimpleNamespace

import networkx as nx
import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite:///tmp/test.db")
os.environ.setdefault("OPENAI_API_KEY", "test")

from app.api.v1 import sessions
from app.services import session_service
from app.services.evaluator_llm import EvaluatorResult
from app.services.rubric_service import MAX_TURNS, RubricScores
from app.services.session_service import _save_session_record


CURRENT_USER = SimpleNamespace(id=1, username="alice")


class FakeDB:
    def __init__(self, record=None):
        self.record = record
        self.committed = False

    def add(self, record):
        self.record = record
        record.id = 42

    def commit(self):
        self.committed = True

    def refresh(self, record):
        record.id = getattr(record, "id", 42)

    def query(self, _model):
        return FakeQuery(self.record)


class FakeQuery:
    def __init__(self, record):
        self.record = record

    def filter(self, *_args, **_kwargs):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.record


def test_save_session_record_stores_scores_and_kg_snapshots():
    db = FakeDB()
    before = {"nodes": [{"id": "TCP", "status": "partial"}], "edges": []}
    after = {"nodes": [{"id": "TCP", "status": "confirmed"}], "edges": []}
    scores = {"concept": 3, "accuracy": 2, "logic": 3, "specificity": 2}

    record_id = _save_session_record(
        db=db,
        document_id=1,
        topic="TCP",
        total_score=10,
        scores=scores,
        turn_count=4,
        termination_reason="score",
        coverage_percent=50.0,
        misconceptions=["오개념"],
        session_summary={"coverage": {"coverage_percent": 50.0}, "missing_nodes": ["ACK"]},
        user_kg_before=before,
        user_kg_after=after,
    )

    assert record_id == 42
    assert db.committed is True
    assert db.record.scores == scores
    assert db.record.user_kg_before == before
    assert db.record.user_kg_after == after


def test_get_session_report_returns_saved_kg_snapshots():
    created_at = datetime(2026, 6, 7)
    record = SimpleNamespace(
        id=7,
        document_id=3,
        topic="TCP",
        scores={"concept": 3},
        total_score=10,
        turn_count=5,
        coverage_percent=66.6,
        misconceptions=["오개념"],
        session_summary={
            "coverage": {"confirmed_count": 2, "total_count": 3, "coverage_percent": 66.6},
            "missing_nodes": ["ACK"],
        },
        user_kg_before={"nodes": [{"id": "TCP", "status": "partial"}], "edges": []},
        user_kg_after={"nodes": [{"id": "TCP", "status": "confirmed"}], "edges": []},
        created_at=created_at,
    )

    response = sessions.api_get_session_report(7, db=FakeDB(record), current_user=CURRENT_USER)

    assert response.document_id == 3
    assert response.scores == {"concept": 3}
    assert response.coverage["confirmed_count"] == 2
    assert response.missing_nodes == ["ACK"]
    assert response.user_kg_before["nodes"][0]["status"] == "partial"
    assert response.user_kg_after["nodes"][0]["status"] == "confirmed"
    assert response.created_at == created_at


def test_get_session_report_normalizes_confirmed_snapshot_with_unmet_checklist():
    record = SimpleNamespace(
        id=7,
        document_id=3,
        topic="TCP",
        scores={"concept": 3},
        total_score=10,
        turn_count=5,
        coverage_percent=66.6,
        misconceptions=[],
        session_summary=None,
        user_kg_before=None,
        user_kg_after={
            "nodes": [
                {
                    "id": "TCP",
                    "status": "confirmed",
                    "checklist": [
                        {
                            "item": "TCP 설명",
                            "met": False,
                            "source_quote": "TCP는 연결 지향 프로토콜이다.",
                            "page_number": 2,
                        },
                    ],
                },
            ],
            "edges": [],
        },
        created_at=None,
    )

    response = sessions.api_get_session_report(7, db=FakeDB(record), current_user=CURRENT_USER)

    node = response.user_kg_after["nodes"][0]
    assert node["status"] == "partial"
    assert node["met_count"] == 0
    assert node["checklist"][0]["source_quote"] == "TCP는 연결 지향 프로토콜이다."
    assert node["checklist"][0]["page_number"] == 2


def test_get_session_report_handles_legacy_record_without_snapshots():
    record = SimpleNamespace(
        id=8,
        document_id=3,
        topic="TCP",
        scores=None,
        total_score=6,
        turn_count=2,
        coverage_percent=25.0,
        misconceptions=None,
        session_summary=None,
        user_kg_before=None,
        user_kg_after=None,
        created_at=None,
    )

    response = sessions.api_get_session_report(8, db=FakeDB(record), current_user=CURRENT_USER)

    assert response.scores == {}
    assert response.coverage == {"coverage_percent": 25.0}
    assert response.misconceptions == []
    assert response.user_kg_before is None
    assert response.user_kg_after is None


def test_get_session_report_404_for_missing_record():
    with pytest.raises(HTTPException) as exc:
        sessions.api_get_session_report(999, db=FakeDB(None), current_user=CURRENT_USER)

    assert exc.value.status_code == 404


def test_process_turn_ends_session_at_turn_limit(monkeypatch):
    reference_kg = nx.DiGraph()
    reference_kg.add_node(
        "TCP",
        status="reference",
        checklist=[{"item": "TCP 설명", "source_quote": "TCP는 연결 지향 프로토콜이다."}],
    )
    user_kg = nx.DiGraph()
    user_kg.add_node(
        "TCP",
        status="missing",
        checklist=[{"item": "TCP 설명", "source_quote": "TCP는 연결 지향 프로토콜이다."}],
        checklist_result=[],
        completion_ratio=0.0,
    )

    saved = {}

    def save_record(**kwargs):
        saved.update(kwargs)
        return 99

    def fail_question(*_args, **_kwargs):
        raise AssertionError("turn limit should not request another student question")

    monkeypatch.setattr(session_service, "load_kg_from_db", lambda _db, _document_id: (reference_kg, user_kg))
    monkeypatch.setattr(session_service, "_retrieve_rag_chunks", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        session_service,
        "evaluate_explanation",
        lambda **_kwargs: EvaluatorResult(updated_user_kg={"nodes": [], "edges": []}, misconceptions=[]),
    )
    monkeypatch.setattr(session_service, "compute_rubric_scores", lambda *_args, **_kwargs: RubricScores(1, 1, 1, 1))
    monkeypatch.setattr(session_service, "save_kg_to_db", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_build_user_kg_view", lambda *_args, **_kwargs: {"nodes": [], "edges": []})
    monkeypatch.setattr(session_service, "_save_session_record", save_record)
    monkeypatch.setattr(session_service, "generate_session_closing_message", lambda **_kwargs: "세션을 마무리할게요.")
    monkeypatch.setattr(session_service, "generate_student_question", fail_question)

    result = session_service.process_turn(
        topic="TCP",
        document_id=1,
        user_explanation="TCP 설명",
        conversation_history=[],
        session_history=[],
        turn_count=MAX_TURNS,
        db=object(),
        initial_user_kg={"nodes": [], "edges": []},
    )

    assert result.is_session_done is True
    assert result.termination_reason == "turn_limit"
    assert result.next_question is None
    assert result.session_record_id == 99
    assert saved["termination_reason"] == "turn_limit"
    assert saved["turn_count"] == MAX_TURNS
