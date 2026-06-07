from typing import Generator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.user import User


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


def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    """Return the logged-in user identified by the lightweight frontend header."""
    if not x_user_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    user = db.query(User).filter(User.username == x_user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="유효하지 않은 사용자입니다.")

    return user
