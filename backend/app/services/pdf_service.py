"""
services/pdf_service.py
-----------------------
PDF 텍스트 추출 및 청킹 서비스.

[변경 이력]
  - 청킹 단위를 페이지 단위 → 전체 문서 단위로 변경 (페이지 경계 문맥 단절 방지)
  - 텍스트 전처리 강화 (연속 공백/줄바꿈 정리)
  - 최소 청크 길이 필터 추가 (50자 미만 청크 제거)
  - overlap 기본값 50 → 100 으로 상향 (chunk_size 500의 20%)
"""

import os
import re
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
            text = _clean_text(text)
            if text:
                pages.append((i + 1, text))

    return pages


def _clean_text(text: str) -> str:
    """
    텍스트 노이즈를 제거한다.

    처리 항목:
      - null 바이트 제거
      - 연속된 공백을 단일 공백으로 압축
      - 3개 이상의 연속 줄바꿈을 최대 2개로 압축 (단락 구분 유지)
      - 앞뒤 공백 제거
    """
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)           # 연속 공백/탭 → 단일 공백
    text = re.sub(r"\n{3,}", "\n\n", text)         # 3줄 이상 빈 줄 → 2줄로
    return text.strip()


def chunk_text(
    text: str,
    chunk_size: int = None,
    overlap: int = None,
    min_chunk_len: int = 50,
) -> List[str]:
    """
    텍스트를 chunk_size 글자 단위로 분할한다.
    overlap만큼 앞 청크와 내용을 겹쳐 문맥이 끊기지 않도록 한다.

    Args:
        text          : 분할할 원본 텍스트
        chunk_size    : 청크 최대 글자 수 (기본값: config.chunk_size = 500)
        overlap       : 겹치는 글자 수   (기본값: config.chunk_overlap = 100)
        min_chunk_len : 이 길이 미만 청크는 버림 (기본값: 50)
                        너무 짧은 청크는 RAG 검색 품질을 떨어뜨림

    Returns:
        청크 텍스트 리스트
    """
    chunk_size = chunk_size or settings.chunk_size
    overlap    = overlap    or settings.chunk_overlap

    chunks: List[str] = []
    start = 0

    while start < len(text):
        end   = start + chunk_size
        chunk = text[start:end].strip()

        # 최소 길이 미만 청크 제거 (그림 캡션, 표 제목 등 노이즈 방지)
        if len(chunk) >= min_chunk_len:
            chunks.append(chunk)

        start += chunk_size - overlap

    return chunks


def extract_and_chunk_pdf(file_path: str) -> List[dict]:
    """
    PDF 파일에서 텍스트를 추출하고 청킹까지 수행한다.
    서비스 레이어에서 이 함수 하나만 호출하면 된다.

    [변경] 청킹 단위: 페이지별 독립 → 전체 문서 합산 후 청킹
    → 페이지 경계에서 개념 설명이 끊기는 문제 해결

    page_number 처리:
      각 청크가 시작되는 글자 위치를 기준으로
      원래 어느 페이지에서 왔는지를 역산해 기록한다.

    Returns:
        [
            {
                "content"     : "청크 텍스트",
                "chunk_index" : 0,
                "page_number" : 1,   # 청크 시작 위치가 속한 페이지
            },
            ...
        ]
    """
    pages = extract_text_from_pdf(file_path)

    if not pages:
        return []

    # 전체 텍스트를 하나로 합치되, 페이지 경계 위치를 기록해둠
    # → 나중에 청크가 어느 페이지에서 시작됐는지 역산할 때 사용
    full_text   = ""
    page_starts = []   # [(char_offset, page_number), ...]

    for page_number, page_text in pages:
        page_starts.append((len(full_text), page_number))
        full_text += page_text + "\n\n"   # 페이지 사이에 빈 줄 삽입

    # 전체 텍스트를 한 번에 청킹
    raw_chunks = chunk_text(full_text)

    result: List[dict] = []
    char_pos = 0   # full_text 내 현재 청크의 시작 위치 추적

    chunk_size = settings.chunk_size
    overlap    = settings.chunk_overlap

    for chunk_index, chunk in enumerate(raw_chunks):
        # 이 청크가 full_text의 어느 위치에서 시작됐는지 계산
        chunk_start = full_text.find(chunk, char_pos)
        if chunk_start == -1:
            chunk_start = char_pos   # fallback

        # 청크 시작 위치에 해당하는 페이지 번호 역산
        page_number = _find_page_number(chunk_start, page_starts)

        result.append({
            "content"     : chunk,
            "chunk_index" : chunk_index,
            "page_number" : page_number,
        })

        # 다음 청크 탐색 시작 위치 업데이트 (overlap 고려)
        char_pos = chunk_start + chunk_size - overlap

    return result


def _find_page_number(char_offset: int, page_starts: List[Tuple[int, int]]) -> int:
    """
    full_text 내 글자 위치(char_offset)가 몇 번째 페이지에 속하는지 반환한다.

    page_starts: [(시작_위치, 페이지_번호), ...] — 오름차순 정렬 상태
    """
    page_number = page_starts[0][1]   # 기본값: 첫 번째 페이지

    for start_offset, pnum in page_starts:
        if char_offset >= start_offset:
            page_number = pnum
        else:
            break

    return page_number


def save_uploaded_file(file_bytes: bytes, filename: str) -> str:
    """
    업로드된 PDF 파일을 uploads 폴더에 저장하고 저장 경로를 반환한다.
    같은 이름의 파일이 있으면 덮어쓰지 않도록 파일명 앞에 타임스탬프를 붙인다.
    """
    import time

    os.makedirs(settings.upload_dir, exist_ok=True)

    safe_filename = f"{int(time.time())}_{filename}"
    file_path = os.path.join(settings.upload_dir, safe_filename)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    return file_path