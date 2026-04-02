from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    """PDF 업로드 API 응답 스키마"""
    id: int
    filename: str
    status: str
    chunk_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentStatusResponse(BaseModel):
    """Document 처리 상태 조회 응답"""
    id: int
    filename: str
    status: str            # pending / processing / done / failed
    chunk_count: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True
