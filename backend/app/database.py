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
    from app.models import document, chunk, session_record, user  # noqa: F401 — 임포트로 모델 등록
    Base.metadata.create_all(bind=engine)

    # 기존 개발 DB는 create_all만으로 새 컬럼이 추가되지 않으므로 보정한다.
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_file_hash ON documents (file_hash)"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id INTEGER"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_user_id ON documents (user_id)"))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_documents_user_id_users'
                ) THEN
                    ALTER TABLE documents
                    ADD CONSTRAINT fk_documents_user_id_users
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
                END IF;
            END $$;
        """))
        conn.execute(text("ALTER TABLE session_records ADD COLUMN IF NOT EXISTS scores JSON"))
        conn.execute(text("ALTER TABLE session_records ADD COLUMN IF NOT EXISTS user_kg_before JSON"))
        conn.execute(text("ALTER TABLE session_records ADD COLUMN IF NOT EXISTS user_kg_after JSON"))
        conn.commit()
