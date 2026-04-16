"""
services/embedding_service.py
------------------------------
청크 임베딩 생성 및 DB 저장 서비스.

[변경 이력]
  - 배치 크기 제한 추가 (BATCH_SIZE=100): 청크 수가 많아도 안전하게 처리
  - 재시도 로직 추가 (최대 3회): 일시적 API 오류에 대한 복원력 확보
  - 배치 단위 로깅 추가: 진행 상황 추적 가능
"""

import logging
import time
from typing import List

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.models.chunk import Chunk
from app.models.document import Document

logger = logging.getLogger(__name__)

client = OpenAI(api_key=settings.openai_api_key)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM   = 1536

# 한 번의 API 호출로 처리할 최대 청크 수
# OpenAI 임베딩 API 제한: 2048개 / 실질 안전 한도: 100개
BATCH_SIZE = 100

# API 호출 실패 시 재시도 횟수 및 대기 시간
MAX_RETRIES    = 3
RETRY_DELAY_S  = 2.0


def get_embedding(text: str) -> List[float]:
    """텍스트 1개에 대한 임베딩 벡터를 반환한다."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    텍스트 여러 개를 배치 단위로 나눠 임베딩한다.

    변경 전: 전체 청크를 한 번에 전송 → 청크 수가 많으면 타임아웃 위험
    변경 후: BATCH_SIZE(100)개씩 나눠 전송 → 안정적 처리 보장

    각 배치는 최대 MAX_RETRIES(3)회 재시도.
    모든 재시도 실패 시 예외를 다시 발생시켜 업로드를 failed 처리.

    Returns:
        임베딩 벡터 리스트 (입력 순서 유지)
    """
    all_embeddings: List[List[float]] = []
    total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end   = start + BATCH_SIZE
        batch = texts[start:end]

        logger.info(
            "임베딩 배치 %d/%d 처리 중 (청크 %d~%d)",
            batch_idx + 1, total_batches, start, min(end, len(texts)) - 1,
        )

        batch_embeddings = _embed_with_retry(batch)
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


def _embed_with_retry(texts: List[str]) -> List[List[float]]:
    """
    단일 배치에 대해 임베딩 API를 호출한다.
    실패 시 MAX_RETRIES회까지 재시도한다.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=texts,
            )
            # API 응답은 index 순서로 정렬되어 있음
            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [e.embedding for e in sorted_data]

        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY_S * attempt   # 점진적 대기: 2s → 4s → 6s
                logger.warning(
                    "임베딩 API 호출 실패 (시도 %d/%d) — %s초 후 재시도: %s",
                    attempt, MAX_RETRIES, wait, e,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "임베딩 API 호출 %d회 모두 실패: %s", MAX_RETRIES, e
                )

    raise RuntimeError(
        f"임베딩 생성 실패 (최대 재시도 {MAX_RETRIES}회 초과): {last_error}"
    )


def embed_and_save_chunks(
    db: Session,
    document: Document,
    chunk_data_list: List[dict],
) -> int:
    """
    청크 데이터에 임베딩을 생성하고 DB에 저장한다.

    Args:
        db              : SQLAlchemy DB 세션
        document        : 연결할 Document 객체
        chunk_data_list : pdf_service.extract_and_chunk_pdf()의 반환값

    Returns:
        저장된 청크 개수
    """
    if not chunk_data_list:
        return 0

    texts      = [c["content"] for c in chunk_data_list]
    embeddings = get_embeddings_batch(texts)   # 배치 분할 + 재시도 포함

    chunks = []
    for chunk_data, embedding in zip(chunk_data_list, embeddings):
        chunk = Chunk(
            document_id = document.id,
            content     = chunk_data["content"],
            chunk_index = chunk_data["chunk_index"],
            page_number = chunk_data.get("page_number"),
            embedding   = embedding,
        )
        chunks.append(chunk)

    db.add_all(chunks)
    db.commit()

    logger.info("청크 %d개 DB 저장 완료 (document_id=%d)", len(chunks), document.id)
    return len(chunks)