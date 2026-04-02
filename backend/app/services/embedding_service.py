from typing import List

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.models.chunk import Chunk
from app.models.document import Document

# OpenAI 클라이언트 (모듈 로드 시 1회 생성)
client = OpenAI(api_key=settings.openai_api_key)

# 사용할 임베딩 모델
EMBEDDING_MODEL = "text-embedding-3-small"
# text-embedding-3-small의 출력 차원
EMBEDDING_DIM = 1536


def get_embedding(text: str) -> List[float]:
    """
    텍스트 1개에 대한 임베딩 벡터를 반환한다.

    Returns:
        1536차원 float 리스트
    """
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    텍스트 여러 개를 한 번의 API 호출로 임베딩한다.
    OpenAI API는 배치 입력을 지원하므로 청크가 많을수록 효율적이다.

    Returns:
        임베딩 벡터 리스트 (입력 순서 유지)
    """
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    # API 응답은 index 순서로 정렬되어 있음
    embeddings = sorted(response.data, key=lambda x: x.index)
    return [e.embedding for e in embeddings]


def embed_and_save_chunks(
    db: Session,
    document: Document,
    chunk_data_list: List[dict],
) -> int:
    """
    청크 데이터에 임베딩을 생성하고 DB에 저장한다.

    Args:
        db: SQLAlchemy DB 세션
        document: 연결할 Document 객체
        chunk_data_list: pdf_service.extract_and_chunk_pdf()의 반환값

    Returns:
        저장된 청크 개수
    """
    if not chunk_data_list:
        return 0

    # 배치 임베딩: 모든 청크 텍스트를 한 번에 전송
    texts = [c["content"] for c in chunk_data_list]
    embeddings = get_embeddings_batch(texts)

    # Chunk 객체 생성 및 DB 추가
    chunks = []
    for chunk_data, embedding in zip(chunk_data_list, embeddings):
        chunk = Chunk(
            document_id=document.id,
            content=chunk_data["content"],
            chunk_index=chunk_data["chunk_index"],
            page_number=chunk_data.get("page_number"),
            embedding=embedding,
        )
        chunks.append(chunk)

    db.add_all(chunks)
    db.commit()

    return len(chunks)
