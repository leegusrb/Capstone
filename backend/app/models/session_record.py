from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.database import Base


class SessionRecord(Base):
    """세션 1회 종료 시 저장되는 이력 레코드."""
    __tablename__ = "session_records"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic = Column(String(500), nullable=False)
    total_score = Column(Integer, nullable=False, default=0)   # 마지막 턴 총점 (0-12)
    turn_count = Column(Integer, nullable=False, default=0)
    termination_reason = Column(String(50), nullable=True)     # score / repetition / turn_limit / user
    coverage_percent = Column(Float, nullable=True)
    misconceptions = Column(JSON, nullable=True)               # list[str]
    scores = Column(JSON, nullable=True)                       # 최종 루브릭 점수 dict
    user_kg_before = Column(JSON, nullable=True)               # 세션 시작 직전 User KG view
    user_kg_after = Column(JSON, nullable=True)                # 세션 종료 시점 User KG view
    session_summary = Column(JSON, nullable=True)              # 전체 요약 dict
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="session_records")
