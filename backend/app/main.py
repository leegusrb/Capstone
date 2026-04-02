from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.api.v1 import documents


app = FastAPI(
    title="Capstone — 페인만 기법 자기주도학습 서비스",
    version="0.1.0",
)

# CORS 설정 — React 개발 서버(5173)에서 요청 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(documents.router, prefix="/api/v1")


@app.on_event("startup")
def on_startup():
    """서버 시작 시 pgvector 활성화 + 테이블 생성"""
    init_db()


@app.get("/health")
def health_check():
    """서버 상태 확인용"""
    return {"status": "ok"}
