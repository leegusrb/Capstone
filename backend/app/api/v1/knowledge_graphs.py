from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.knowledge_graph import KnowledgeGraph
from app.models.document import Document
from app.core.exceptions import DocumentNotFoundError
from app.services.kg_service import (
    deserialize_kg,
    get_kg_coverage,
    get_missing_nodes,
    get_student_context,
    strip_internal_fields_from_kg_dict,
)
from fastapi import HTTPException

router = APIRouter(prefix="/knowledge-graphs", tags=["knowledge-graphs"])


def _get_kg_or_404(db: Session, document_id: int) -> KnowledgeGraph:
    """document_id로 KG 레코드를 조회하고 없으면 404를 반환하는 공통 헬퍼."""
    # Document 존재 여부 먼저 확인
    if not db.query(Document).filter(Document.id == document_id).first():
        raise DocumentNotFoundError(document_id)

    kg_record = db.query(KnowledgeGraph).filter_by(document_id=document_id).first()
    if not kg_record:
        raise HTTPException(
            status_code=404,
            detail=f"Document ID {document_id}의 Knowledge Graph가 아직 생성되지 않았습니다.",
        )
    return kg_record


@router.get("/{document_id}")
def get_knowledge_graph(
    document_id: int,
    db: Session = Depends(get_db),
):
    """
    document_id에 해당하는 Reference KG와 User KG를 JSON으로 반환한다.

    Response:
    {
      "document_id": 1,
      "reference_kg": {
        "nodes": [{"id": "TCP", "status": "reference"}, ...],
        "edges": [{"source": "TCP", "target": "흐름 제어", "relation": "포함", ...}]
      },
      "user_kg": {
        "nodes": [{"id": "TCP", "status": "confirmed"}, ...],
        "edges": [{"source": "TCP", "target": "흐름 제어", "relation": "포함", "status": "partial"}, ...]
      },
      "coverage": {
        "confirmed_count": 2,
        "total_count": 6,
        "coverage_percent": 33.3
      },
      "missing_nodes": ["혼잡 제어", "ACK", "3-way handshake"],
      "student_context": {
        "confirmed_nodes": ["TCP"],
        "partial_nodes":   ["흐름 제어"],
        "confirmed_edges": [...],
        "partial_edges":   [...]
      }
    }
    """
    kg_record = _get_kg_or_404(db, document_id)

    reference_kg = deserialize_kg(kg_record.reference_kg or {"nodes": [], "edges": []})
    user_kg      = deserialize_kg(kg_record.user_kg      or {"nodes": [], "edges": []})

    # 체크리스트 원문은 사용자에게 노출하지 않는다 (PDF §4-1, §12-5).
    # met_count / total_count 형태의 정량 정보만 남긴다.
    return {
        "document_id":    document_id,
        "reference_kg":   strip_internal_fields_from_kg_dict(kg_record.reference_kg or {"nodes": [], "edges": []}),
        "user_kg":        strip_internal_fields_from_kg_dict(kg_record.user_kg      or {"nodes": [], "edges": []}),
        "coverage":       get_kg_coverage(user_kg, reference_kg),
        "missing_nodes":  get_missing_nodes(user_kg),
        "student_context": get_student_context(user_kg),
    }


@router.get("/{document_id}/reference")
def get_reference_kg(
    document_id: int,
    db: Session = Depends(get_db),
):
    """Reference KG만 반환한다 (체크리스트 원문 제외)."""
    kg_record = _get_kg_or_404(db, document_id)
    return {
        "document_id":  document_id,
        "reference_kg": strip_internal_fields_from_kg_dict(kg_record.reference_kg or {"nodes": [], "edges": []}),
    }


@router.get("/{document_id}/user")
def get_user_kg(
    document_id: int,
    db: Session = Depends(get_db),
):
    """
    User KG와 학습 진행 현황을 반환한다.
    세션 종료 화면 또는 프론트엔드 KG 시각화에서 사용.
    체크리스트 원문은 노출되지 않으며, met_count/total_count로 진행도만 노출된다.
    """
    kg_record = _get_kg_or_404(db, document_id)

    reference_kg = deserialize_kg(kg_record.reference_kg or {"nodes": [], "edges": []})
    user_kg      = deserialize_kg(kg_record.user_kg      or {"nodes": [], "edges": []})

    return {
        "document_id":  document_id,
        "user_kg":      strip_internal_fields_from_kg_dict(kg_record.user_kg or {"nodes": [], "edges": []}),
        "coverage":     get_kg_coverage(user_kg, reference_kg),
        "missing_nodes": get_missing_nodes(user_kg),
    }