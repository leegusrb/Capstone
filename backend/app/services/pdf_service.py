import os
from typing import List, Tuple

import PyPDF2

from app.config import settings


def extract_text_from_pdf(file_path: str) -> List[Tuple[int, str]]:
    """
    PDF 파일에서 페이지별 텍스트를 추출한다.

    Returns:
        [(page_number, text), ...] — 1-indexed 페이지 번호
    """
    pages: List[Tuple[int, str]] = []

    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = text.strip()
            if text:  # 빈 페이지는 건너뜀
                pages.append((i + 1, text))

    return pages


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
    """
    텍스트를 chunk_size 글자 단위로 분할한다.
    overlap만큼 앞 청크와 내용을 겹쳐 문맥이 끊기지 않도록 한다.

    Args:
        text: 분할할 원본 텍스트
        chunk_size: 청크 최대 글자 수 (기본값: config에서 읽음)
        overlap: 겹치는 글자 수 (기본값: config에서 읽음)

    Returns:
        청크 텍스트 리스트
    """
    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap

    chunks: List[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        # 다음 청크 시작점: overlap만큼 뒤로 당겨서 문맥 연결
        start += chunk_size - overlap

    return chunks


def extract_and_chunk_pdf(file_path: str) -> List[dict]:
    """
    PDF 파일에서 텍스트를 추출하고 청킹까지 수행한다.
    서비스 레이어에서 이 함수 하나만 호출하면 된다.

    Returns:
        [
            {
                "content": "청크 텍스트",
                "chunk_index": 0,
                "page_number": 1
            },
            ...
        ]
    """
    pages = extract_text_from_pdf(file_path)

    result: List[dict] = []
    chunk_index = 0

    for page_number, page_text in pages:
        chunks = chunk_text(page_text)
        for chunk in chunks:
            result.append({
                "content": chunk,
                "chunk_index": chunk_index,
                "page_number": page_number,
            })
            chunk_index += 1

    return result


def save_uploaded_file(file_bytes: bytes, filename: str) -> str:
    """
    업로드된 PDF 파일을 uploads 폴더에 저장하고 저장 경로를 반환한다.
    같은 이름의 파일이 있으면 덮어쓰지 않도록 파일명 앞에 타임스탬프를 붙인다.
    """
    import time

    os.makedirs(settings.upload_dir, exist_ok=True)

    # 파일명 충돌 방지: 타임스탬프_원본파일명
    safe_filename = f"{int(time.time())}_{filename}"
    file_path = os.path.join(settings.upload_dir, safe_filename)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    return file_path
