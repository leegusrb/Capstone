from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str

    # OpenAI
    openai_api_key: str

    # 파일 업로드
    upload_dir: str = "uploads"

    # 청킹 설정
    chunk_size: int = 500       # 청크 1개당 최대 글자 수
    chunk_overlap: int = 50     # 청크 간 겹치는 글자 수

    class Config:
        env_file = ".env"


# 앱 전역에서 settings 인스턴스를 가져다 쓴다
settings = Settings()
