from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str

    # OpenAI
    openai_api_key: str
    stt_model: str = "gpt-4o-mini-transcribe"

    # 파일 업로드
    upload_dir: str = "uploads"

    # CORS
    cors_origins: str = "http://localhost:5173"

    # 청킹 설정
    chunk_size: int    = 500   # 청크 1개당 최대 글자 수
    chunk_overlap: int = 100   # 청크 간 겹치는 글자 수 (chunk_size의 20%)
    #                            변경 전: 50 (10%) → 변경 후: 100 (20%)
    #                            overlap이 너무 작으면 청크 경계에서 문맥이 단절됨

    debug_mode: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    class Config:
        env_file = ".env"


settings = Settings()
