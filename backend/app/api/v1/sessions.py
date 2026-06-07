"""
api/v1/sessions.py
-------------------
세션 관련 FastAPI 라우터.

엔드포인트:
  POST /api/v1/sessions/start  : 세션 시작 → Student LLM 첫 질문 반환
  POST /api/v1/sessions/turn   : 사용자 설명 처리 → Evaluator 채점 + 다음 질문
  POST /api/v1/sessions/end    : 사용자 직접 종료 → 세션 요약 반환

main.py에 다음 한 줄 추가:
  from app.api.v1 import sessions
  app.include_router(sessions.router, prefix="/api/v1")
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import DocumentNotFoundError
from app.models.document import Document
from app.models.session_record import SessionRecord
from app.services.session_service import (
    TurnResult,
    end_session_early,
    process_turn,
    start_session,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── 요청 스키마 ────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    document_id: int = Field(..., description="업로드된 PDF의 Document ID")
    topic: str       = Field(..., description="학습 주제 (예: 'TCP/IP 네트워크')")


class TurnRequest(BaseModel):
    document_id:      int        = Field(..., description="Document ID")
    topic:            str        = Field(..., description="학습 주제")
    user_explanation: str        = Field(..., description="사용자가 입력한 이번 턴 설명")
    conversation_history: list[dict] = Field(
        default=[],
        description=(
            "이번 세션의 전체 대화 기록. "
            "[{\"role\": \"assistant\"|\"user\", \"content\": \"...\"}] 형식. "
            "프론트엔드에서 매 턴 누적해서 전달."
        ),
    )
    session_history: list[dict] = Field(
        default=[],
        description=(
            "이전 턴의 점수 기록 리스트. "
            "[{\"concept\": int, \"accuracy\": int, \"logic\": int, \"specificity\": int}] 형식. "
            "프론트엔드에서 매 턴 누적해서 전달."
        ),
    )
    turn_count: int = Field(default=1, ge=1, description="현재 턴 번호 (1-indexed)")
    initial_user_kg: dict | None = Field(
        default=None,
        description="세션 시작 직전 User KG 스냅샷. 세션 종료 리포트의 BEFORE 그래프로 저장.",
    )


class EndSessionRequest(BaseModel):
    document_id:     int        = Field(..., description="Document ID")
    topic:           str        = Field(..., description="학습 주제")
    session_history: list[dict] = Field(
        default=[],
        description="지금까지의 점수 기록 리스트",
    )
    initial_user_kg: dict | None = Field(
        default=None,
        description="세션 시작 직전 User KG 스냅샷. 세션 종료 리포트의 BEFORE 그래프로 저장.",
    )


# ── 응답 스키마 ────────────────────────────────────────────

class StartSessionResponse(BaseModel):
    first_question: str
    initial_user_kg: dict | None = None


class TurnResponse(BaseModel):
    # 이번 턴 평가 결과
    scores:         dict
    total:          int
    misconceptions: list[dict]

    # 다음 질문 (세션이 계속되는 경우)
    next_question: str | None = None

    # 세션 종료 정보
    is_session_done:    bool
    termination_reason: str | None = None
    session_summary:    dict | None = None
    closing_message:    str  | None = None

    # KG 현황 (프론트엔드 실시간 시각화용)
    coverage:      dict      | None = None
    missing_nodes: list[str] | None = None
    session_record_id: int | None = None


class EndSessionResponse(BaseModel):
    scores:          dict
    total:           int
    session_summary: dict
    closing_message: str
    coverage:        dict
    missing_nodes:   list[str]
    session_record_id: int | None = None


class SessionReportResponse(BaseModel):
    document_id: int
    topic: str
    scores: dict
    total: int
    turn_count: int
    coverage: dict
    missing_nodes: list[str]
    misconceptions: list
    user_kg_before: dict | None = None
    user_kg_after: dict | None = None
    created_at: datetime | None = None


# ── 헬퍼 ──────────────────────────────────────────────────

def _get_ready_document(db: Session, document_id: int) -> Document:
    """
    Document가 존재하고 처리 완료 상태인지 확인한다.
    없거나 처리 중이면 적절한 HTTP 에러를 반환한다.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise DocumentNotFoundError(document_id)
    if doc.status != "done":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Document {document_id}의 처리가 아직 완료되지 않았습니다. "
                f"현재 상태: {doc.status}. 잠시 후 다시 시도하세요."
            ),
        )
    return doc


# ── 엔드포인트 ─────────────────────────────────────────────

@router.post("/start", response_model=StartSessionResponse)
def api_start_session(
    body: StartSessionRequest,
    db: Session = Depends(get_db),
):
    """
    세션을 시작하고 Student LLM의 첫 질문을 반환한다.

    - document_id에 해당하는 실제 KG(User KG)를 DB에서 로드합니다.
    - 현재 User KG의 confirmed/partial 상태를 반영한 첫 질문을 생성합니다.
      (이미 학습한 세션이 있다면 이어서 질문합니다.)
    """
    _get_ready_document(db, body.document_id)

    result = start_session(
        topic=body.topic,
        document_id=body.document_id,
        db=db,
    )
    return StartSessionResponse(
        first_question=result.first_question,
        initial_user_kg=result.initial_user_kg,
    )


@router.post("/turn", response_model=TurnResponse)
def api_process_turn(
    body: TurnRequest,
    db: Session = Depends(get_db),
):
    """
    사용자 설명 1턴을 처리한다.

    처리 순서:
      1. DB에서 실제 Reference KG / User KG 로드
      2. 사용자 설명으로 RAG 유사도 검색 (실제 문서 청크 반환)
      3. Evaluator LLM — 실제 KG 기반 채점 + User KG 업데이트 결정
      4. 업데이트된 User KG를 DB에 저장
      5. is_sufficient 확인:
         - True  → 세션 요약 + Student 마무리 메시지 생성
         - False → Student LLM 다음 질문 생성

    프론트엔드 책임:
      - conversation_history: 매 턴 assistant/user 메시지를 누적해서 전달
      - session_history: 매 턴 응답의 scores를 누적해서 다음 요청에 포함
      - turn_count: 1부터 시작해서 매 턴 +1
    """
    _get_ready_document(db, body.document_id)

    result: TurnResult = process_turn(
        topic=body.topic,
        document_id=body.document_id,
        user_explanation=body.user_explanation,
        conversation_history=body.conversation_history,
        session_history=body.session_history,
        turn_count=body.turn_count,
        db=db,
        initial_user_kg=body.initial_user_kg,
    )

    return TurnResponse(
        scores=result.scores,
        total=result.total,
        misconceptions=result.misconceptions,
        next_question=result.next_question,
        is_session_done=result.is_session_done,
        termination_reason=result.termination_reason,
        session_summary=result.session_summary,
        closing_message=result.closing_message,
        coverage=result.coverage,
        missing_nodes=result.missing_nodes,
        session_record_id=result.session_record_id,
    )


@router.post("/end", response_model=EndSessionResponse)
def api_end_session(
    body: EndSessionRequest,
    db: Session = Depends(get_db),
):
    """
    사용자가 직접 세션을 종료할 때 호출한다.

    - 현재까지의 session_history를 바탕으로 세션 요약을 생성합니다.
    - DB의 실제 User KG 커버리지를 기반으로 마무리 메시지를 생성합니다.
    - User KG는 변경하지 않습니다 (다음 세션에서 이어서 사용).
    """
    _get_ready_document(db, body.document_id)

    result: TurnResult = end_session_early(
        topic=body.topic,
        document_id=body.document_id,
        session_history=body.session_history,
        db=db,
        initial_user_kg=body.initial_user_kg,
    )

    return EndSessionResponse(
        scores=result.scores,
        total=result.total,
        session_summary=result.session_summary or {},
        closing_message=result.closing_message or "",
        coverage=result.coverage or {},
        missing_nodes=result.missing_nodes or [],
        session_record_id=result.session_record_id,
    )


@router.get("/{session_id}/report", response_model=SessionReportResponse)
def api_get_session_report(
    session_id: int,
    db: Session = Depends(get_db),
):
    """저장된 세션 리포트 데이터를 반환한다."""
    record = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"SessionRecord ID {session_id}를 찾을 수 없습니다.",
        )

    summary = record.session_summary or {}
    coverage = summary.get("coverage") or {
        "coverage_percent": record.coverage_percent or 0.0,
    }

    return SessionReportResponse(
        document_id=record.document_id,
        topic=record.topic,
        scores=record.scores or {},
        total=record.total_score,
        turn_count=record.turn_count,
        coverage=coverage,
        missing_nodes=summary.get("missing_nodes") or [],
        misconceptions=record.misconceptions or [],
        user_kg_before=record.user_kg_before,
        user_kg_after=record.user_kg_after,
        created_at=record.created_at,
    )
