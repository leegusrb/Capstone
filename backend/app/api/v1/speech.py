from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.speech_service import transcribe_audio


router = APIRouter(prefix="/speech", tags=["speech"])

MAX_AUDIO_FILE_SIZE_BYTES = 25 * 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = {".webm", ".wav", ".mp3", ".m4a"}


class TranscriptionResponse(BaseModel):
    text: str


def _validate_audio_file(filename: str | None, file_bytes: bytes) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_AUDIO_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"오디오 파일만 업로드할 수 있습니다. 허용 확장자: {allowed}",
        )

    if not file_bytes:
        raise HTTPException(status_code=400, detail="오디오 파일이 비어 있습니다.")

    if len(file_bytes) > MAX_AUDIO_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="파일 크기는 25MB를 초과할 수 없습니다.")


@router.post("/transcribe", response_model=TranscriptionResponse)
async def api_transcribe_audio(
    file: UploadFile = File(...),
    topic: str = Form(default=""),
):
    file_bytes = await file.read()
    _validate_audio_file(file.filename, file_bytes)

    text = transcribe_audio(
        audio_bytes=file_bytes,
        filename=file.filename or "audio.webm",
        content_type=file.content_type,
        topic=topic,
    )
    return TranscriptionResponse(text=text)
