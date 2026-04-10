import os

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import InvalidFileTypeError, FileTooLargeError, DocumentNotFoundError
from app.models.document import Document
from app.schemas.document import DocumentUploadResponse, DocumentStatusResponse
from app.services.pdf_service import save_uploaded_file, extract_and_chunk_pdf
from app.services.embedding_service import embed_and_save_chunks
from app.services.kg_service import (
    build_reference_kg,
    init_user_kg,
    save_kg_to_db,
)

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    PDF 파일을 업로드하고 청킹 + 임베딩 + KG 생성을 수행한다.

    처리 순서:
    1. 파일 유효성 검사 (PDF 여부, 크기 제한)
    2. uploads/ 폴더에 파일 저장
    3. Document 레코드 생성 (status=processing)
    4. PDF 텍스트 추출 + 청킹
    5. 청크 임베딩 생성 + DB 저장
    6. Reference KG 생성 (LLM 호출)       ← 추가
    7. User KG 초기화 (모든 노드 missing)   ← 추가
    8. KG DB 저장                           ← 추가
    9. Document status를 done으로 업데이트
    """

    # 1. 파일 유효성 검사
    if not file.filename.endswith(".pdf"):
        raise InvalidFileTypeError()

    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(max_mb=20)

    # 2. 파일 저장
    file_path = save_uploaded_file(file_bytes, file.filename)

    # 3. Document 레코드 생성
    document = Document(
        filename=file.filename,
        file_path=file_path,
        status="processing",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        # 4. PDF 텍스트 추출 + 청킹
        chunk_data_list = extract_and_chunk_pdf(file_path)

        # 5. 임베딩 생성 + DB 저장
        chunk_count = embed_and_save_chunks(db, document, chunk_data_list)

        # 6. Reference KG 생성 — 청크 텍스트만 추출해서 LLM에 전달
        text_chunks = [c["content"] for c in chunk_data_list]
        reference_kg = build_reference_kg(text_chunks)

        # 7. User KG 초기화 — Reference KG의 모든 노드/엣지를 missing 상태로 복사
        user_kg = init_user_kg(reference_kg)

        # 8. KG DB 저장
        save_kg_to_db(db, document.id, reference_kg, user_kg)

        # 9. 완료 상태 업데이트
        document.status = "done"
        db.commit()
        db.refresh(document)

    except Exception as e:
        document.status = "failed"
        db.commit()
        raise e

    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        chunk_count=chunk_count,
        created_at=document.created_at,
    )


@router.get("/{document_id}", response_model=DocumentStatusResponse)
def get_document_status(
    document_id: int,
    db: Session = Depends(get_db),
):
    """Document 처리 상태를 조회한다."""
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise DocumentNotFoundError(document_id)

    chunk_count = len(document.chunks) if document.chunks else 0

    return DocumentStatusResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        chunk_count=chunk_count,
        created_at=document.created_at,
    )