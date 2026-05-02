from typing import Generator

from sqlalchemy.orm import Session

from app.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI 라우터에서 DB 세션을 주입받을 때 사용하는 의존성 함수.

    사용 예시:
        @router.post("/upload")
        def upload(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
