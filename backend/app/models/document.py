from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Document(Base):
    """
    사용자가 업로드한 PDF 학습 자료.
    - 1개 Document → N개 Chunk (1:N 관계)
    - 1개 Document → 1개 KnowledgeGraph (1:1 관계)
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)

    filename  = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)

    # 업로드 상태: pending / processing / done / failed
    status = Column(String(20), nullable=False, default="pending")

    raw_text   = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Chunk 관계 (Document 삭제 시 Chunk도 함께 삭제)
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")

    # KnowledgeGraph 관계 (Document 삭제 시 KG도 함께 삭제)
    knowledge_graph = relationship(
        "KnowledgeGraph",
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,   # 1:1 관계이므로 리스트 아님
    )