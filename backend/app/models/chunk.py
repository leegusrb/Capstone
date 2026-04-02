from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.database import Base


class Chunk(Base):
    """
    Document에서 분할된 텍스트 청크.
    - embedding 컬럼에 pgvector로 1536차원 벡터 저장
      (text-embedding-3-small 출력 차원 = 1536)
    """
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)

    # 어느 Document에서 왔는지
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)

    # 청크 텍스트 본문
    content = Column(Text, nullable=False)

    # Document 내 청크 순서 (0부터 시작)
    chunk_index = Column(Integer, nullable=False)

    # 임베딩 벡터 (text-embedding-3-small → 1536차원)
    embedding = Column(Vector(1536), nullable=True)

    # RAG 검색 시 출처 표시용 (예: "3페이지")
    page_number = Column(Integer, nullable=True)

    # Document와의 관계
    document = relationship("Document", back_populates="chunks")
