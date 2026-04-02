"""
pdf_service 단위 테스트.
실제 PDF 파일 없이도 chunk_text 로직을 검증한다.
"""
import pytest
from app.services.pdf_service import chunk_text


def test_chunk_text_basic():
    """청크 크기보다 짧은 텍스트는 1개 청크로 반환되어야 한다."""
    text = "안녕하세요. 이것은 테스트 텍스트입니다."
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert chunks[0] == text.strip()


def test_chunk_text_splits_correctly():
    """청크 크기를 초과하는 텍스트는 여러 청크로 분할되어야 한다."""
    # 100글자짜리 텍스트를 chunk_size=30, overlap=5로 분할
    text = "가" * 100
    chunks = chunk_text(text, chunk_size=30, overlap=5)
    assert len(chunks) > 1


def test_chunk_text_overlap():
    """overlap 설정 시 인접 청크가 내용을 공유해야 한다."""
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 26글자
    chunks = chunk_text(text, chunk_size=10, overlap=3)
    # 첫 번째 청크의 끝 3글자가 두 번째 청크의 앞에 포함되어야 함
    assert chunks[0][-3:] == chunks[1][:3]


def test_chunk_text_empty():
    """빈 텍스트는 빈 리스트를 반환해야 한다."""
    chunks = chunk_text("", chunk_size=500, overlap=50)
    assert chunks == []
