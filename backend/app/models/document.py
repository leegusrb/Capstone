from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Document(Base):
    """
    사용자가 업로드한 PDF 학습 자료.
    - 1개 Document → N개 Chunk (1:N 관계)
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)

    # 원본 파일명 (사용자가 올린 그대로)
    filename = Column(String(255), nullable=False)

    # 서버에 저장된 실제 파일 경로
    file_path = Column(String(500), nullable=False)

    # 업로드 상태: pending / processing / done / failed
    status = Column(String(20), nullable=False, default="pending")

    # 추출된 전체 텍스트 (옵션 — 디버깅 용도)
    raw_text = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Chunk와의 관계 (Document 삭제 시 관련 Chunk도 함께 삭제)
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
