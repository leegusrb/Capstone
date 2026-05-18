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

from app.models.session_record import SessionRecord
from app.services.kg_service import (
    get_best_scores,
    get_kg_coverage,
    get_missing_nodes,
    get_specificity_state,
    get_student_context,
    load_kg_from_db,
    save_kg_to_db,
    update_best_scores,
    update_specificity_state,
    update_user_kg_from_evaluator,
)
from app.services.evaluator_llm import (
    EvaluatorResult,
    RubricScores,
    SCORE_THRESHOLD,
    SCORE_CATEGORIES,
    build_session_summary,
    compute_rubric_scores,
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
    scores:         dict
    total:          int
    misconceptions: list[dict]

    next_question: Optional[str] = None

    is_session_done:    bool          = False
    termination_reason: Optional[str] = None  # "score"|"repetition"|"turn_limit"|"user"

    session_summary: Optional[dict] = None
    closing_message: Optional[str]  = None

    coverage:      Optional[dict]      = None
    missing_nodes: Optional[list[str]] = None
    evaluator_kg_updates: Optional[list[dict]] = None  # Evaluator가 반환한 raw 노드 상태
    student_context: Optional[dict] = None  # Student LLM에 전달된 컨텍스트 (디버그용)


@dataclass
class StartSessionResult:
    """start_session()의 반환값."""
    first_question: str


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
    kgs = load_kg_from_db(db, document_id)
    if not kgs:
        raise ValueError(f"Document {document_id}의 KG가 존재하지 않습니다. 먼저 PDF를 업로드하세요.")

    _, user_kg = kgs
    student_context = get_student_context(user_kg)

    student_resp = generate_student_question(
        topic=topic,
        student_context=student_context,
        conversation_history=[],
        model=model,
    )

    logger.info(
        "세션 시작 — document_id: %d | 주제: %s",
        document_id, topic,
    )

    return StartSessionResult(
        first_question=student_resp.question,
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
    # ── 1. 실제 KG 로드 ──
    kgs = load_kg_from_db(db, document_id)
    if not kgs:
        raise ValueError(f"Document {document_id}의 KG가 존재하지 않습니다.")
    reference_kg, user_kg = kgs

    # 이전 세션까지의 최고 점수 (KG에 저장된 값)
    best_scores = get_best_scores(user_kg)

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

    # ── 4. User KG 업데이트 ──
    user_kg = update_user_kg_from_evaluator(user_kg, {
        "updated_user_kg": eval_result.updated_user_kg,
        "misconceptions":  eval_result.misconceptions,
    })

    # ── 5. 구체성 체크리스트 누적 업데이트 ──
    accumulated_specificity = get_specificity_state(user_kg)
    merged_specificity = {
        k: eval_result.specificity_checklist.get(k, False) or accumulated_specificity.get(k, False)
        for k in set(accumulated_specificity) | set(eval_result.specificity_checklist)
    }
    update_specificity_state(user_kg, merged_specificity)

    # ── 6. 업데이트된 KG 기반 루브릭 점수 계산 (구체성은 누적 체크리스트 사용) ──
    scores = compute_rubric_scores(user_kg, reference_kg, merged_specificity)

    # 누적 보장: concept/accuracy/logic은 이전 최고 점수를 floor로 적용
    scores = RubricScores(
        concept     = max(scores.concept,     best_scores.get("concept",     0)),
        accuracy    = max(scores.accuracy,    best_scores.get("accuracy",    0)),
        logic       = max(scores.logic,       best_scores.get("logic",       0)),
        specificity = scores.specificity,  # KG 누적으로 자체 보장
    )

    # 갱신된 점수를 KG에 저장 (다음 세션 floor로 사용)
    update_best_scores(user_kg, scores.to_dict())
    save_kg_to_db(db, document_id, reference_kg, user_kg)

    total = scores.total
    is_sufficient = total >= SCORE_THRESHOLD
    termination_reason = "score" if is_sufficient else None
    weak_areas = [cat for cat in SCORE_CATEGORIES if scores.to_dict().get(cat, 0) <= 1]

    coverage      = get_kg_coverage(user_kg, reference_kg)
    missing_nodes = get_missing_nodes(user_kg)

    # ── 6. 세션 종료 분기 ──
    if is_sufficient:
        updated_history = session_history + [scores.to_dict()]
        summary = build_session_summary(
            session_history=updated_history,
            user_kg=user_kg,
            reference_kg=reference_kg,
            termination_reason=termination_reason,
        )
        closing = generate_session_closing_message(
            topic=topic,
            termination_reason=termination_reason,
            session_summary=summary,
            model=model,
        )
        logger.info(
            "세션 종료 — 사유: %s | 총점: %d | 커버리지: %.1f%%",
            termination_reason, total, coverage.get("coverage_percent", 0),
        )
        _save_session_record(
            db=db,
            document_id=document_id,
            topic=topic,
            total_score=total,
            turn_count=turn_count,
            termination_reason=termination_reason,
            coverage_percent=coverage.get("coverage_percent", 0.0),
            misconceptions=[m.get("description", str(m)) for m in eval_result.misconceptions],
            session_summary=summary,
        )
        return TurnResult(
            scores=scores.to_dict(),
            total=total,
            misconceptions=eval_result.misconceptions,
            is_session_done=True,
            termination_reason=termination_reason,
            session_summary=summary,
            closing_message=closing,
            coverage=coverage,
            missing_nodes=missing_nodes,
        )

    # ── 7. 다음 질문 생성 ──
    student_context = get_student_context(user_kg)

    next_student: StudentResponse = generate_student_question(
        topic=topic,
        student_context=student_context,
        conversation_history=conversation_history,
        model=model,
    )

    logger.info("턴 %d 완료 — 총점: %d | weak: %s", turn_count, total, weak_areas)

    return TurnResult(
        scores=scores.to_dict(),
        total=total,
        misconceptions=eval_result.misconceptions,
        next_question=next_student.question,
        is_session_done=False,
        coverage=coverage,
        missing_nodes=missing_nodes,
        evaluator_kg_updates=eval_result.updated_user_kg.get("nodes", []),
        student_context=student_context,
    )


def _save_session_record(
    db: DBSession,
    document_id: int,
    topic: str,
    total_score: int,
    turn_count: int,
    termination_reason: str,
    coverage_percent: float,
    misconceptions: list,
    session_summary: dict,
) -> None:
    record = SessionRecord(
        document_id=document_id,
        topic=topic,
        total_score=total_score,
        turn_count=turn_count,
        termination_reason=termination_reason,
        coverage_percent=coverage_percent,
        misconceptions=misconceptions,
        session_summary=session_summary,
    )
    db.add(record)
    db.commit()


def end_session_early(
    topic: str,
    document_id: int,
    session_history: list[dict],
    db: DBSession,
    model: str = "gpt-5.4-mini",
) -> TurnResult:
    kgs = load_kg_from_db(db, document_id)
    if not kgs:
        raise ValueError(f"Document {document_id}의 KG가 존재하지 않습니다.")
    reference_kg, user_kg = kgs

    # KG에 누적된 구체성 체크리스트로 점수 계산
    accumulated_specificity = get_specificity_state(user_kg)
    scores_obj = compute_rubric_scores(user_kg, reference_kg, accumulated_specificity)
    coverage = get_kg_coverage(user_kg, reference_kg)

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

    avg_total = scores_obj.total

    _save_session_record(
        db=db,
        document_id=document_id,
        topic=topic,
        total_score=avg_total,
        turn_count=len(session_history),
        termination_reason="user",
        coverage_percent=coverage.get("coverage_percent", 0.0),
        misconceptions=[],
        session_summary=summary,
    )

    return TurnResult(
        scores=scores_obj.to_dict(),
        total=avg_total,
        misconceptions=[],
        is_session_done=True,
        termination_reason="user",
        session_summary=summary,
        closing_message=closing,
        coverage=coverage,
        missing_nodes=get_missing_nodes(user_kg),
    )
