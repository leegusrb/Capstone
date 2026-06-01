from io import BytesIO

from openai import OpenAI

from app.config import settings


STT_MODEL = settings.stt_model

_openai_client = OpenAI(api_key=settings.openai_api_key)


def _build_transcription_prompt(topic: str | None) -> str:
    topic_text = (topic or "학습 주제").strip() or "학습 주제"
    return (
        "한국어 학습 설명을 정확히 받아쓰기 해주세요. "
        f"주제: {topic_text}. "
        "전공 용어와 약어는 가능한 한 원문 표기를 유지하세요."
    )


def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    content_type: str | None,
    topic: str | None = None,
) -> str:
    audio_file = BytesIO(audio_bytes)
    audio_file.name = filename
    normalized_content_type = (content_type or "application/octet-stream").split(";", 1)[0]

    result = _openai_client.audio.transcriptions.create(
        model=STT_MODEL,
        file=(filename, audio_file, normalized_content_type),
        response_format="text",
        language="ko",
        prompt=_build_transcription_prompt(topic),
    )

    if isinstance(result, str):
        return result.strip()
    return (result.text or "").strip()
