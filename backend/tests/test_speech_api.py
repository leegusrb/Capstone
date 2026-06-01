from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import speech
from app.services import speech_service


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(speech.router, prefix="/api/v1")
    return TestClient(app)


def test_transcribe_audio_calls_openai_with_context(monkeypatch):
    calls = []

    class FakeTranscriptions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return " TCP는 연결 지향 프로토콜입니다. "

    class FakeAudio:
        transcriptions = FakeTranscriptions()

    class FakeClient:
        audio = FakeAudio()

    monkeypatch.setattr(speech_service, "_openai_client", FakeClient())

    text = speech_service.transcribe_audio(
        audio_bytes=b"audio",
        filename="teacher-mode.webm",
        content_type="audio/webm",
        topic="TCP/IP 네트워크",
    )

    assert text == "TCP는 연결 지향 프로토콜입니다."
    assert calls[0]["model"] == speech_service.STT_MODEL
    assert calls[0]["response_format"] == "text"
    assert calls[0]["language"] == "ko"
    assert calls[0]["file"][0] == "teacher-mode.webm"
    assert calls[0]["file"][2] == "audio/webm"
    assert "TCP/IP 네트워크" in calls[0]["prompt"]


def test_transcribe_endpoint_returns_text(monkeypatch):
    def fake_transcribe_audio(audio_bytes, filename, content_type, topic):
        assert audio_bytes == b"audio"
        assert filename == "teacher-mode.webm"
        assert content_type == "audio/webm"
        assert topic == "TCP/IP"
        return "변환된 텍스트"

    monkeypatch.setattr(speech, "transcribe_audio", fake_transcribe_audio)

    client = make_client()
    response = client.post(
        "/api/v1/speech/transcribe",
        data={"topic": "TCP/IP"},
        files={"file": ("teacher-mode.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "변환된 텍스트"}


def test_transcribe_endpoint_rejects_empty_file(monkeypatch):
    monkeypatch.setattr(speech, "transcribe_audio", lambda *args, **kwargs: "unused")

    client = make_client()
    response = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("teacher-mode.webm", b"", "audio/webm")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "오디오 파일이 비어 있습니다."


def test_transcribe_endpoint_rejects_non_audio_extension(monkeypatch):
    monkeypatch.setattr(speech, "transcribe_audio", lambda *args, **kwargs: "unused")

    client = make_client()
    response = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("teacher-mode.txt", b"audio", "text/plain")},
    )

    assert response.status_code == 400
    assert "오디오 파일만" in response.json()["detail"]


def test_transcribe_endpoint_rejects_large_file(monkeypatch):
    monkeypatch.setattr(speech, "transcribe_audio", lambda *args, **kwargs: "unused")
    monkeypatch.setattr(speech, "MAX_AUDIO_FILE_SIZE_BYTES", 4)

    client = make_client()
    response = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("teacher-mode.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "파일 크기는 25MB를 초과할 수 없습니다."
