from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.api.v1 import documents, knowledge_graphs, sessions


app = FastAPI(
    title="Capstone — 페인만 기법 자기주도학습 서비스",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router,        prefix="/api/v1")
app.include_router(knowledge_graphs.router, prefix="/api/v1")
app.include_router(sessions.router,         prefix="/api/v1")


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health_check():
    return {"status": "ok"}