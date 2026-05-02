from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# SQLAlchemy 엔진 생성
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # 연결이 끊겼을 때 자동 재연결
    echo=False,           # SQL 로그 출력 여부 (개발 중 True로 바꾸면 편함)
)

# 세션 팩토리
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모든 ORM 모델이 상속받을 Base 클래스
Base = declarative_base()


def get_db():
    """FastAPI 의존성 주입용 DB 세션 제공 함수"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    앱 시작 시 pgvector 확장 활성화 + 테이블 생성.
    Alembic을 붙이기 전 개발 초기 단계에서 사용.
    """
    # pgvector extension 활성화 (최초 1회만 실행됨)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # Base에 등록된 모든 모델 테이블 생성
    from app.models import document, chunk  # noqa: F401 — 임포트로 모델 등록
    Base.metadata.create_all(bind=engine)
