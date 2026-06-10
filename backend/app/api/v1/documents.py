import hashlib
import logging
import os
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.exceptions import InvalidFileTypeError, FileTooLargeError, DocumentNotFoundError
from app.database import SessionLocal
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.knowledge_graph import KnowledgeGraph
from app.models.session_record import SessionRecord
from app.models.user import User
from app.schemas.document import DocumentUploadResponse, DocumentStatusResponse
from app.services.pdf_service import save_uploaded_file, extract_and_chunk_pdf
from app.services.embedding_service import embed_and_save_chunks
from app.services.kg_service import (
    deserialize_kg,
    init_user_kg,
    save_kg_to_db,
)
from app.services.reference_kg_generator import generate_reference_kg

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB
PAGE_MARKER_RE = re.compile(r"^\[page_number=\d+\]$")


def _has_page_marker_node(kg_data: dict | None) -> bool:
    if not kg_data:
        return False
    return any(
        PAGE_MARKER_RE.fullmatch(str(node.get("id", "")).strip())
        for node in kg_data.get("nodes", [])
        if isinstance(node, dict)
    )


def _get_owned_document(db: Session, document_id: int, user_id: int) -> Document:
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.user_id == user_id)
        .first()
    )
    if not document:
        raise DocumentNotFoundError(document_id)
    return document


def _find_cached_document(db: Session, file_hash: str, user_id: int) -> Document | None:
    """같은 PDF 해시로 이미 완료된 문서를 찾는다."""
    cached_documents = (
        db.query(Document)
        .join(KnowledgeGraph, KnowledgeGraph.document_id == Document.id)
        .filter(
            Document.file_hash == file_hash,
            Document.user_id == user_id,
            Document.status == "done",
            KnowledgeGraph.reference_kg.isnot(None),
        )
        .order_by(Document.created_at.desc())
        .all()
    )
    for document in cached_documents:
        if _has_page_marker_node(document.knowledge_graph.reference_kg):
            continue
        return document
    return None


def _copy_chunks(db: Session, source: Document, target: Document) -> int:
    """캐시된 문서의 청크와 임베딩을 새 문서에 복사한다."""
    copied = []
    for chunk in sorted(source.chunks, key=lambda c: c.chunk_index):
        embedding = chunk.embedding
        copied.append(Chunk(
            document_id=target.id,
            content=chunk.content,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
            embedding=list(embedding) if embedding is not None else None,
        ))

    if copied:
        db.add_all(copied)
        db.commit()

    return len(copied)


def _process_document_upload(db: Session, document: Document) -> int:
    cached_document = _find_cached_document(db, document.file_hash, document.user_id)

    if cached_document:
        # 같은 사용자의 같은 PDF는 기존 Reference KG를 재사용해 KG 흔들림을 방지한다.
        chunk_count = _copy_chunks(db, cached_document, document)
        reference_kg = deserialize_kg(cached_document.knowledge_graph.reference_kg)
        user_kg = init_user_kg(reference_kg)
        save_kg_to_db(db, document.id, reference_kg, user_kg)
        return chunk_count

    chunk_data_list = extract_and_chunk_pdf(document.file_path)
    chunk_count = embed_and_save_chunks(db, document, chunk_data_list)
    reference_kg = generate_reference_kg(chunk_data_list)
    user_kg = init_user_kg(reference_kg)
    save_kg_to_db(db, document.id, reference_kg, user_kg)
    return chunk_count


def process_document_upload_background(document_id: int) -> None:
    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            logger.warning("백그라운드 문서 처리 대상이 없습니다. document_id=%d", document_id)
            return

        try:
            _process_document_upload(db, document)
            document.status = "done"
            db.commit()
        except Exception:
            logger.exception("문서 처리 실패. document_id=%d", document_id)
            document.status = "failed"
            db.commit()
    finally:
        db.close()


@router.get("", response_model=List[DocumentStatusResponse])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """업로드된 문서 목록을 최신순으로 반환한다."""
    documents = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [
        DocumentStatusResponse(
            id=doc.id,
            filename=doc.filename,
            status=doc.status,
            chunk_count=len(doc.chunks) if doc.chunks else 0,
            created_at=doc.created_at,
        )
        for doc in documents
    ]


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    PDF 파일을 업로드하고 백그라운드에서 청킹 + 임베딩 + KG 생성을 수행한다.

    처리 순서:
    1. 파일 유효성 검사 (PDF 여부, 크기 제한)
    2. uploads/ 폴더에 파일 저장
    3. Document 레코드 생성 (status=processing)
    4. 백그라운드 작업 등록 후 즉시 응답
    """
    if not file.filename.endswith(".pdf"):
        raise InvalidFileTypeError()

    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(max_mb=20)

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    file_path = save_uploaded_file(file_bytes, file.filename)

    document = Document(
        user_id=current_user.id,
        filename=file.filename,
        file_path=file_path,
        file_hash=file_hash,
        status="processing",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    background_tasks.add_task(process_document_upload_background, document.id)

    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        chunk_count=0,
        created_at=document.created_at,
    )


@router.get("/{document_id}", response_model=DocumentStatusResponse)
def get_document_status(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Document 처리 상태를 조회한다."""
    document = _get_owned_document(db, document_id, current_user.id)

    chunk_count = len(document.chunks) if document.chunks else 0

    return DocumentStatusResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        chunk_count=chunk_count,
        created_at=document.created_at,
    )


class SessionRecordResponse(BaseModel):
    id: int
    topic: str
    total_score: int
    turn_count: int
    termination_reason: Optional[str]
    coverage_percent: Optional[float]
    misconceptions: Optional[List[str]]
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentDeleteResponse(BaseModel):
    id: int
    deleted: bool


@router.get("/{document_id}/sessions", response_model=List[SessionRecordResponse])
def list_document_sessions(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 문서의 세션 이력을 최신순으로 반환한다."""
    _get_owned_document(db, document_id, current_user.id)

    records = (
        db.query(SessionRecord)
        .filter(SessionRecord.document_id == document_id)
        .order_by(SessionRecord.created_at.desc())
        .all()
    )
    return records


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """문서와 해당 문서의 KG, 청크, 세션 이력을 삭제한다."""
    document = _get_owned_document(db, document_id, current_user.id)

    file_path = document.file_path
    db.delete(document)
    db.commit()

    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass

    return DocumentDeleteResponse(id=document_id, deleted=True)
