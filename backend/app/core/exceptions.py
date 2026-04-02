from fastapi import HTTPException


class InvalidFileTypeError(HTTPException):
    """PDF가 아닌 파일을 업로드했을 때"""
    def __init__(self):
        super().__init__(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")


class FileTooLargeError(HTTPException):
    """파일 크기 초과"""
    def __init__(self, max_mb: int = 20):
        super().__init__(
            status_code=400,
            detail=f"파일 크기는 {max_mb}MB를 초과할 수 없습니다."
        )


class DocumentNotFoundError(HTTPException):
    """Document ID로 조회했을 때 없는 경우"""
    def __init__(self, document_id: int):
        super().__init__(
            status_code=404,
            detail=f"Document ID {document_id}를 찾을 수 없습니다."
        )
