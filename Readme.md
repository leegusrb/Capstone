# Capstone — 페인만 기법 기반 자기주도학습 서비스

## 프로젝트 구조

```
capstone/
├── backend/          # FastAPI 백엔드
├── frontend/         # React + Vite 프론트엔드
└── docker-compose.yml
```

---

## 시작하기

### 1. PostgreSQL (pgvector) 실행

```bash
docker-compose up -d
```

### 2. 백엔드 설정 및 실행

```bash
cd backend

# 환경변수 설정
cp .env.example .env
# .env 파일에서 OPENAI_API_KEY 입력

# 패키지 설치
pip install -r requirements.txt

# 서버 실행
uvicorn app.main:app --reload
```

서버: http://localhost:8000  
API 문서: http://localhost:8000/docs

### 3. 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
```

앱: http://localhost:5173

---

## 이번 주 구현 범위 (PDF 업로드 → 청킹 → 임베딩)

| 엔드포인트 | 설명 |
|---|---|
| `POST /api/v1/documents/upload` | PDF 업로드 + 청킹 + 임베딩 |
| `GET /api/v1/documents/{id}` | 처리 상태 조회 |
| `GET /health` | 서버 상태 확인 |

## 기술 스택

| 분야 | 기술 |
|---|---|
| 백엔드 | FastAPI, SQLAlchemy, pgvector |
| 프론트엔드 | React, Vite |
| DB | PostgreSQL + pgvector |
| AI | OpenAI API (text-embedding-3-small) |
| PDF 처리 | PyPDF2 |