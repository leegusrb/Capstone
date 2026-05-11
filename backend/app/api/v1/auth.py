import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ── 스키마 ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str  = Field(..., min_length=1, max_length=100, description="로그인 아이디")
    password: str  = Field(..., min_length=6)
    name:     str  = Field(..., min_length=1, max_length=100)
    email:    EmailStr


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id:       str   # 프론트엔드 AuthContext의 user.id (= username)
    name:     str
    email:    str


# ── 엔드포인트 ─────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """회원가입 — 아이디 및 이메일 중복 시 409 반환."""
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="이미 사용 중인 이메일입니다.")

    user = User(
        username=body.username,
        password_hash=_hash(body.password),
        name=body.name,
        email=body.email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse(id=user.username, name=user.name, email=user.email)


@router.post("/login", response_model=UserResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """로그인 — 아이디·비밀번호 불일치 시 401 반환."""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not _verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

    return UserResponse(id=user.username, name=user.name, email=user.email)
