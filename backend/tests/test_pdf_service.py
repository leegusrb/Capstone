"""
pdf_service 단위 테스트.
실제 PDF 파일 없이도 청킹 로직을 검증한다.
"""
from app.services.pdf_service import chunk_text, _clean_text


def test_chunk_text_basic():
    """청크 크기보다 짧은 텍스트는 1개 청크로 반환되어야 한다."""
    text = "안녕하세요. 이것은 테스트 텍스트입니다."
    # min_chunk_len=1: 필터를 끄고 순수 청킹 로직만 검증
    chunks = chunk_text(text, chunk_size=500, overlap=100, min_chunk_len=1)
    assert len(chunks) == 1
    assert chunks[0] == text.strip()


def test_chunk_text_splits_correctly():
    """청크 크기를 초과하는 텍스트는 여러 청크로 분할되어야 한다."""
    text = "가" * 100
    # min_chunk_len=1: 30자 청크가 필터되지 않도록
    chunks = chunk_text(text, chunk_size=30, overlap=5, min_chunk_len=1)
    assert len(chunks) > 1


def test_chunk_text_overlap():
    """overlap 설정 시 인접 청크가 내용을 공유해야 한다."""
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 26글자
    chunks = chunk_text(text, chunk_size=10, overlap=3, min_chunk_len=1)
    assert chunks[0][-3:] == chunks[1][:3]


def test_chunk_text_empty():
    """빈 텍스트는 빈 리스트를 반환해야 한다."""
    chunks = chunk_text("", chunk_size=500, overlap=100)
    assert chunks == []


def test_chunk_text_min_length_filter():
    """min_chunk_len 미만 청크는 제거되어야 한다."""
    # 40자 텍스트를 chunk_size=500으로 → 1개 청크지만 min_chunk_len=50 미만 → 제거
    text = "가" * 40
    chunks = chunk_text(text, chunk_size=500, overlap=100, min_chunk_len=50)
    assert len(chunks) == 0


def test_clean_text_removes_null_bytes():
    """\x00 바이트가 제거되어야 한다."""
    text = "안녕\x00하세요"
    assert "\x00" not in _clean_text(text)


def test_clean_text_collapses_whitespace():
    """연속 공백이 단일 공백으로 압축되어야 한다."""
    text = "안녕   하세요"
    cleaned = _clean_text(text)
    assert "   " not in cleaned
    assert "안녕 하세요" == cleaned


def test_clean_text_collapses_newlines():
    """3줄 이상 연속 줄바꿈이 2줄로 압축되어야 한다."""
    text = "A\n\n\n\nB"
    cleaned = _clean_text(text)
    assert "\n\n\n" not in cleaned
    assert "A\n\nB" == cleaned


if __name__ == "__main__":
    test_chunk_text_basic()
    test_chunk_text_splits_correctly()
    test_chunk_text_overlap()
    test_chunk_text_empty()
    test_chunk_text_min_length_filter()
    test_clean_text_removes_null_bytes()
    test_clean_text_collapses_whitespace()
    test_clean_text_collapses_newlines()
    print("🎉 모든 테스트 통과")