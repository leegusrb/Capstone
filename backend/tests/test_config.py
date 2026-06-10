import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from app.config import Settings


def test_sqlalchemy_database_url_accepts_railway_postgres_scheme():
    settings = Settings(
        database_url="postgres://user:pass@example.railway.internal:5432/db",
        openai_api_key="test-key",
    )

    assert settings.sqlalchemy_database_url == (
        "postgresql://user:pass@example.railway.internal:5432/db"
    )


def test_sqlalchemy_database_url_keeps_postgresql_scheme():
    settings = Settings(
        database_url="postgresql://user:pass@example.railway.internal:5432/db",
        openai_api_key="test-key",
    )

    assert settings.sqlalchemy_database_url == (
        "postgresql://user:pass@example.railway.internal:5432/db"
    )
