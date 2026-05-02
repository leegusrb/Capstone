"""
services/session_service.py
----------------------------
Student LLM과 Evaluator LLM을 연결하는 세션 오케스트레이터.

매 턴 처리 흐름:
  1. DB에서 실제 KG 로드 (reference_kg, user_kg)
  2. RAG 검색 — 사용자 설명과 유사한 실제 청크 조회
  3. Evaluator LLM — 실제 KG 기반 채점 + User KG 업데이트
  4. 업데이트된 User KG DB 저장
  5. 세션 종료 여부 확인 (eval_result.is_sufficient)
     - 종료 → 세션 요약 + Student 마무리 메시지
     - 계속 → Student LLM 다음 질문 생성
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.services.kg_service import (
    get_kg_coverage,
    get_missing_nodes,
    get_student_context,
    load_kg_from_db,
    save_kg_to_db,
    update_user_kg_from_evaluator,
)
from app.services.evaluator_llm import (
    EvaluatorResult,
    build_session_summary,
    evaluate_explanation,
)
from app.services.student_llm import (
    StudentResponse,
    generate_session_closing_message,
    generate_student_question,
)

logger = logging.getLogger(__name__)


# ── 데이터 클래스 ──────────────────────────────────────────

@dataclass
class TurnResult:
    """process_turn()의 반환값."""
    scores:       dict
    total:        int
    weak_areas:   list[str]
    misconceptions: list[dict]

    next_question: Optional[str] = None
    next_intent:   Optional[str] = None

    is_session_done:    bool          = False
    termination_reason: Optional[str] = None  # "score"|"repetition"|"turn_limit"|"user"

    session_summary: Optional[dict] = None
    closing_message: Optional[str]  = None

    coverage:      Optional[dict]      = None
    missing_nodes: Optional[list[str]] = None


@dataclass
class StartSessionResult:
    """start_session()의 반환값."""
    first_question: str
    intent:         str


# ── RAG 검색 ──────────────────────────────────────────────

def _retrieve_rag_chunks(
    db: DBSession,
    document_id: int,
    query: str,
    top_k: int = 5,
) -> list[str]:
    """
    pgvector 유사도 검색으로 관련 청크를 가져온다.
    rag_service 미구현 시 해당 document의 실제 청크를 순서대로 fallback 사용.
    """
    try:
        from app.services.rag_service import search_similar_chunks  # type: ignore
        results = search_similar_chunks(db, document_id, query, top_k=top_k)
        return [r["content"] for r in results]
    except (ImportError, Exception) as e:
        logger.warning("RAG 서비스 미구현 또는 오류 — fallback 사용: %s", e)
        from app.models.chunk import Chunk
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
            .limit(top_k)
            .all()
        )
        return [c.content for c in chunks]


# ── 진입점 ─────────────────────────────────────────────────

def start_session(
    topic: str,
    document_id: int,
    db: DBSession,
    model: str = "gpt-4o-mini",
) -> StartSessionResult:
    """
    세션을 시작하고 Student LLM의 첫 질문을 반환한다.

    Args:
        topic       : 사용자가 입력한 학습 주제
        document_id : 업로드된 PDF의 Document ID
        db          : DB 세션
        model       : LLM 모델명
    """
    kgs = load_kg_from_db(db, document_id)
    if not kgs:
        raise ValueError(f"Document {document_id}의 KG가 존재하지 않습니다. 먼저 PDF를 업로드하세요.")

    _, user_kg = kgs

    # 현재 User KG에서 confirmed/partial 노드만 추출 (missing 제외)
    student_context = get_student_context(user_kg)

    student_resp = generate_student_question(
        topic=topic,
        student_context=student_context,
        conversation_history=[],   # 첫 턴이므로 대화 없음
        evaluator_feedback="",
        weak_areas=[],
        model=model,
    )

    logger.info(
        "세션 시작 — document_id: %d | 주제: %s | 첫 질문 intent: %s",
        document_id, topic, student_resp.intent,
    )

    return StartSessionResult(
        first_question=student_resp.question,
        intent=student_resp.intent,
    )


def process_turn(
    topic: str,
    document_id: int,
    user_explanation: str,
    conversation_history: list[dict],
    session_history: list[dict],
    turn_count: int,
    db: DBSession,
    model: str = "gpt-4o-mini",
) -> TurnResult:
    """
    사용자 설명 1턴을 처리한다.

    Args:
        topic                : 학습 주제
        document_id          : 업로드된 PDF의 Document ID
        user_explanation     : 이번 턴 사용자 설명 텍스트
        conversation_history : 이번 세션의 전체 대화 기록
        session_history      : 이전 턴의 scores dict 리스트 (반복 한계 판단용)
        turn_count           : 현재 턴 번호 (1-indexed)
        db                   : DB 세션
        model                : LLM 모델명
    """
    # ── 1. 실제 KG 로드 ──
    kgs = load_kg_from_db(db, document_id)
    if not kgs:
        raise ValueError(f"Document {document_id}의 KG가 존재하지 않습니다.")
    reference_kg, user_kg = kgs

    # ── 2. RAG 검색 (실제 문서 청크) ──
    rag_chunks = _retrieve_rag_chunks(db, document_id, query=user_explanation)

    # ── 3. Evaluator LLM — 실제 KG 기반 채점 ──
    eval_result: EvaluatorResult = evaluate_explanation(
        user_explanation=user_explanation,
        user_kg=user_kg,
        reference_kg=reference_kg,
        rag_chunks=rag_chunks,
        session_history=session_history,
        turn_count=turn_count,
        model=model,
    )

    # ── 4. User KG 업데이트 + DB 저장 ──
    user_kg = update_user_kg_from_evaluator(user_kg, {
        "updated_user_kg": eval_result.updated_user_kg,
        "misconceptions":  eval_result.misconceptions,
    })
    save_kg_to_db(db, document_id, reference_kg, user_kg)

    coverage      = get_kg_coverage(user_kg, reference_kg)
    missing_nodes = get_missing_nodes(user_kg)

    # ── 5. 세션 종료 분기 (is_sufficient 사용) ──
    if eval_result.is_sufficient:
        updated_history = session_history + [eval_result.scores.to_dict()]
        summary = build_session_summary(
            session_history=updated_history,
            user_kg=user_kg,
            reference_kg=reference_kg,
            termination_reason=eval_result.termination_reason or "score",
        )
        closing = generate_session_closing_message(
            topic=topic,
            termination_reason=eval_result.termination_reason or "score",
            session_summary=summary,
            model=model,
        )
        logger.info(
            "세션 종료 — 사유: %s | 커버리지: %.1f%%",
            eval_result.termination_reason,
            coverage.get("coverage_percent", 0),
        )
        return TurnResult(
            scores=eval_result.scores.to_dict(),
            total=eval_result.total,
            weak_areas=eval_result.weak_areas,
            misconceptions=eval_result.misconceptions,
            is_session_done=True,
            termination_reason=eval_result.termination_reason,
            session_summary=summary,
            closing_message=closing,
            coverage=coverage,
            missing_nodes=missing_nodes,
        )

    # ── 6. 다음 질문 생성 (세션 계속) ──
    # confirmed/partial 노드만 포함된 컨텍스트 추출 (missing 차단)
    student_context = get_student_context(user_kg)

    next_student: StudentResponse = generate_student_question(
        topic=topic,
        student_context=student_context,
        conversation_history=conversation_history,
        evaluator_feedback=eval_result.feedback_summary,
        weak_areas=eval_result.weak_areas,
        missing_nodes=missing_nodes,
        model=model,
    )

    logger.info(
        "턴 %d 완료 — 총점: %d | 다음 intent: %s",
        turn_count, eval_result.total, next_student.intent,
    )

    return TurnResult(
        scores=eval_result.scores.to_dict(),
        total=eval_result.total,
        weak_areas=eval_result.weak_areas,
        misconceptions=eval_result.misconceptions,
        next_question=next_student.question,
        next_intent=next_student.intent,
        is_session_done=False,
        coverage=coverage,
        missing_nodes=missing_nodes,
    )


def end_session_early(
    topic: str,
    document_id: int,
    session_history: list[dict],
    db: DBSession,
    model: str = "gpt-4o-mini",
) -> TurnResult:
    """
    사용자가 직접 세션을 종료할 때 호출한다.

    Args:
        topic           : 학습 주제
        document_id     : 업로드된 PDF의 Document ID
        session_history : 지금까지의 점수 기록
        db              : DB 세션
        model           : LLM 모델명
    """
    kgs = load_kg_from_db(db, document_id)
    if not kgs:
        raise ValueError(f"Document {document_id}의 KG가 존재하지 않습니다.")
    reference_kg, user_kg = kgs

    summary = build_session_summary(
        session_history=session_history,
        user_kg=user_kg,
        reference_kg=reference_kg,
        termination_reason="user",
    )
    closing = generate_session_closing_message(
        topic=topic,
        termination_reason="user",
        session_summary=summary,
        model=model,
    )

    empty_scores = {"concept": 0, "accuracy": 0, "logic": 0, "specificity": 0}

    return TurnResult(
        scores=empty_scores,
        total=0,
        weak_areas=[],
        misconceptions=[],
        is_session_done=True,
        termination_reason="user",
        session_summary=summary,
        closing_message=closing,
        coverage=get_kg_coverage(user_kg, reference_kg),
        missing_nodes=get_missing_nodes(user_kg),
    )