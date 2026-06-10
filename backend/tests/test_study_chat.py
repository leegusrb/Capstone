import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite:///tmp/test.db")
os.environ.setdefault("OPENAI_API_KEY", "test")

from app.api.v1 import study_chat
from app.services import study_tutor


CURRENT_USER = SimpleNamespace(id=1, username="alice")


class FakeDB:
    def __init__(self, document=None):
        self.document = document

    def query(self, _model):
        return FakeQuery(self.document)


class FakeQuery:
    def __init__(self, document):
        self.document = document

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.document


def _body():
    return study_chat.StudyChatAskRequest(
        document_id=1,
        topic="TCP/IP",
        question="TCP는 무엇인가요?",
        conversation_history=[],
    )


def test_answer_study_question_uses_rag_context_and_gpt_54_mini(monkeypatch):
    calls = []

    def fake_search_similar_chunks(db, document_id, query, top_k):
        assert db == "db"
        assert document_id == 1
        assert query == "TCP는 무엇인가요?"
        assert top_k == 5
        return [{
            "content": "TCP는 연결 지향 프로토콜이다.",
            "chunk_index": 2,
            "page_number": 7,
        }]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="TCP는 연결 지향 프로토콜입니다.")
                )]
            )

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(study_tutor, "search_similar_chunks", fake_search_similar_chunks)
    monkeypatch.setattr(study_tutor, "_openai_client", FakeClient())

    result = study_tutor.answer_study_question(
        db="db",
        document_id=1,
        topic="TCP/IP",
        question="TCP는 무엇인가요?",
        conversation_history=[],
    )

    assert study_tutor.TUTOR_MODEL == "gpt-5.4-mini"
    assert calls[0]["model"] == "gpt-5.4-mini"
    assert "TCP는 연결 지향 프로토콜이다." in calls[0]["messages"][1]["content"]
    assert result.answer == "TCP는 연결 지향 프로토콜입니다."
    assert result.sources == [{"chunk_index": 2, "page_number": 7}]


def test_answer_study_question_handles_empty_rag_results(monkeypatch):
    calls = []

    monkeypatch.setattr(study_tutor, "search_similar_chunks", lambda **_kwargs: [])

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="업로드한 자료만으로는 확인하기 어렵습니다.")
                )]
            )

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(study_tutor, "_openai_client", FakeClient())

    result = study_tutor.answer_study_question(
        db="db",
        document_id=1,
        topic="TCP/IP",
        question="자료에 없는 질문",
        conversation_history=[],
    )

    assert "(관련 자료를 찾지 못했습니다.)" in calls[0]["messages"][1]["content"]
    assert result.answer == "업로드한 자료만으로는 확인하기 어렵습니다."
    assert result.sources == []


def test_ask_study_tutor_returns_answer_for_ready_document(monkeypatch):
    document = SimpleNamespace(id=1, filename="lecture.pdf", status="done")

    def fake_answer_study_question(**kwargs):
        assert kwargs["document_id"] == 1
        assert kwargs["topic"] == "TCP/IP"
        assert kwargs["question"] == "TCP는 무엇인가요?"
        return SimpleNamespace(
            answer="문서 기반 답변",
            sources=[{"chunk_index": 1, "page_number": None}],
        )

    monkeypatch.setattr(study_chat, "answer_study_question", fake_answer_study_question)

    response = study_chat.ask_study_tutor(_body(), db=FakeDB(document), current_user=CURRENT_USER)

    assert response.answer == "문서 기반 답변"
    assert [source.model_dump() for source in response.sources] == [
        {"chunk_index": 1, "page_number": None}
    ]


def test_ask_study_tutor_raises_404_for_missing_document():
    with pytest.raises(HTTPException) as exc:
        study_chat.ask_study_tutor(_body(), db=FakeDB(None), current_user=CURRENT_USER)

    assert exc.value.status_code == 404


def test_ask_study_tutor_raises_400_for_unfinished_document():
    document = SimpleNamespace(id=1, filename="lecture.pdf", status="processing")

    with pytest.raises(HTTPException) as exc:
        study_chat.ask_study_tutor(_body(), db=FakeDB(document), current_user=CURRENT_USER)

    assert exc.value.status_code == 400
    assert "아직 완료되지 않았습니다" in exc.value.detail
