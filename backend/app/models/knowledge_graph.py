from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import relationship

from app.database import Base


class KnowledgeGraph(Base):
    """
    Document 1개에 대응하는 Knowledge Graph 저장소.

    - reference_kg : PDF에서 추출한 기준 KG (업로드 시 1회 생성, 이후 고정)
    - user_kg      : 사용자 설명이 누적되는 동적 KG (세션 간 유지)

    두 KG 모두 serialize_kg()의 반환값(dict)을 그대로 저장한다.
    {
      "nodes": [{"id": "TCP", "status": "reference"}, ...],
      "edges": [{"source": "TCP", "target": "흐름 제어", "relation": "포함", ...}, ...]
    }
    """
    __tablename__ = "knowledge_graphs"

    id = Column(Integer, primary_key=True, index=True)

    # 어느 Document에 속하는지 (1 Document : 1 KnowledgeGraph)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # Document 1개당 KG 1개
        index=True,
    )

    # Reference KG — PDF 업로드 시 LLM이 생성, 이후 변경 없음
    reference_kg = Column(JSON, nullable=True)

    # User KG — 세션마다 Evaluator LLM이 업데이트
    # 초기값: Reference KG의 모든 노드/엣지를 missing 상태로 복사
    user_kg = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Document와의 관계
    document = relationship("Document", back_populates="knowledge_graph")