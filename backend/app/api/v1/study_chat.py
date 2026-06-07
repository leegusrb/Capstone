"""
api/v1/study_chat.py
--------------------
Student mode document-grounded Q&A endpoints.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import DocumentNotFoundError
from app.models.document import Document
from app.services.study_tutor import answer_study_question

router = APIRouter(prefix="/study-chat", tags=["study-chat"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class StudyChatAskRequest(BaseModel):
    document_id: int = Field(..., description="업로드된 PDF의 Document ID")
    topic: str = Field(..., description="학습 주제")
    question: str = Field(..., min_length=1, description="사용자 질문")
    conversation_history: list[ChatMessage] = Field(default_factory=list)


class StudyChatSource(BaseModel):
    chunk_index: int | None = None
    page_number: int | None = None


class StudyChatAskResponse(BaseModel):
    answer: str
    sources: list[StudyChatSource]


def _get_ready_document(db: Session, document_id: int) -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise DocumentNotFoundError(document_id)
    if document.status != "done":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Document {document_id}의 처리가 아직 완료되지 않았습니다. "
                f"현재 상태: {document.status}. 잠시 후 다시 시도하세요."
            ),
        )
    return document


@router.post("/ask", response_model=StudyChatAskResponse)
def ask_study_tutor(
    body: StudyChatAskRequest,
    db: Session = Depends(get_db),
):
    """업로드된 문서 기반으로 학생모드 AI 튜터 답변을 생성한다."""
    _get_ready_document(db, body.document_id)

    result = answer_study_question(
        db=db,
        document_id=body.document_id,
        topic=body.topic,
        question=body.question.strip(),
        conversation_history=[msg.model_dump() for msg in body.conversation_history],
    )

    return StudyChatAskResponse(
        answer=result.answer,
        sources=result.sources,
    )
