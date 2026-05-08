"""
services/rag_service.py
------------------------
pgvector 코사인 유사도 검색으로 관련 청크를 반환하는 RAG 서비스.
"""

import logging

from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.services.embedding_service import get_embedding

logger = logging.getLogger(__name__)


def search_similar_chunks(
    db: Session,
    document_id: int,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """
    쿼리 텍스트와 코사인 유사도가 높은 청크를 top_k개 반환한다.

    Args:
        db          : SQLAlchemy DB 세션
        document_id : 검색 대상 문서 ID
        query       : 사용자 설명 텍스트
        top_k       : 반환할 청크 수

    Returns:
        [{"content": str, "chunk_index": int, "page_number": int|None}, ...]
    """
    query_vector = get_embedding(query)

    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == document_id)
        .filter(Chunk.embedding.isnot(None))
        .order_by(Chunk.embedding.cosine_distance(query_vector))
        .limit(top_k)
        .all()
    )

    if not chunks:
        logger.warning("document_id=%d 에서 임베딩이 있는 청크를 찾지 못했습니다.", document_id)

    logger.info(
        "RAG 검색 완료 — document_id=%d | 반환 청크=%d개",
        document_id, len(chunks),
    )

    return [
        {
            "content": c.content,
            "chunk_index": c.chunk_index,
            "page_number": c.page_number,
        }
        for c in chunks
    ]
