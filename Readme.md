# Tu:gather — 페인만 기법 기반 자기주도학습 서비스

> **"AI에게 설명해보세요. 진짜로 이해했는지 확인할 수 있습니다."**

학습자가 AI 학생 에이전트에게 개념을 설명하면, AI가 사용자의 누적 설명을 학습자료 기반 지식 그래프로 추적하고 평가하며 추가 질문을 이어가는 **페인만 기법 기반 자기주도학습 웹 서비스**입니다.

---

## 📑 목차

- [핵심 아이디어](#-핵심-아이디어)
- [기존 서비스와의 차이](#-기존-서비스와의-차이)
- [시스템 아키텍처](#-시스템-아키텍처)
- [지식 그래프 설계](#-지식-그래프-knowledge-graph)
- [Reference KG 품질 방어선](#-reference-kg-품질-방어선)
- [평가 루브릭](#-평가-루브릭)
- [세션 종료 조건](#-세션-종료-조건)
- [기술 스택](#-기술-스택)
- [프로젝트 구조](#-프로젝트-구조)
- [시작하기](#-시작하기)
- [현재 개발 상태](#-현재-개발-상태)
- [팀 구성](#-팀-구성)

---

## ✨ 핵심 아이디어

기존 AI 학습 도구는 **"질문 → 답변"** 구조입니다. 학습자는 수동적으로 정보를 받아들이게 됩니다.

이 서비스는 그 방향을 뒤집습니다.

> **학습자가 AI에게 설명합니다.**

AI는 답을 주는 튜터가 아닌, **해당 주제에 대해 진짜로 아무것도 모르는 학생 에이전트**입니다.
단순히 "모르는 척"하는 것이 아니라, 사용자가 설명한 내용만을 지식 그래프로 누적해 기억하며,
설명받지 않은 개념은 **아키텍처 수준에서 접근 자체가 차단**됩니다.

---

## 🆚 기존 서비스와의 차이

| 구분 | 기존 서비스 | 본 서비스 |
|---|---|---|
| **구조** | 질문 → 답변 제공 | 설명 → 누적 평가 → 추가 질문 → 재설명 |
| **사용자 역할** | 수동적 정보 수신자 | 능동적 설명자 |
| **AI 역할** | 답을 주는 튜터 | 진짜로 모르는 학생 에이전트 |
| **맥락 처리** | 매 턴 독립적 처리 | Knowledge Graph로 세션 간 맥락 누적 유지 |
| **평가 기준** | 없음 | 학습자료 기반 루브릭 평가 (Evaluator LLM) |
| **AI 구조** | 단일 LLM | Student LLM + Evaluator LLM 2-에이전트 |
| **이해도 추적** | 없음 | Reference KG ↔ User KG 비교를 통한 구조적 분석 |
| **학습 단위** | 단일 대화 | 멀티 세션 (세션 간 KG 누적) |

---

## 🏗️ 시스템 아키텍처

### 2-에이전트 구조

```
┌─────────────────────────────────────────────┐
│                  사용자                       │
│            "TCP는 연결 지향..."               │
└──────────────────┬──────────────────────────┘
                   │ 설명 입력
         ┌─────────┴──────────┐
         ▼                    ▼
┌─────────────────┐  ┌──────────────────────┐
│  Student LLM    │  │   Evaluator LLM      │
│  (학생 에이전트)   │  │   (평가자 에이전트)    │
│                 │  │                      │
│ • 사전 지식 없음   │  │ • RAG 학습자료 보유    │
│ • confirmed /   │  │ • 루브릭 4개 영역      │
│   partial만     │  │   채점                │
│   참조 가능      │  │ • User KG 업데이트    │
│ • missing 노드   │  │ • 세션 종료 판단       │
│   접근 불가      │  │ • 백그라운드 처리       │
│ • 사용자에게      │  │                      │
│   직접 노출      │  │                      │
└────────┬────────┘  └──────────┬───────────┘
         │                      │
         │         User KG 공유  │
         ▼                      ▼
┌─────────────────────────────────────────────┐
│     Knowledge Graph (User KG) — 세션 간 누적   │
│                                              │
│  confirmed:     TCP → 연결 지향 (정확)         │
│  partial:       TCP → 흐름 제어 (관계 모호)     │
│  missing:       TCP → 혼잡 제어                │
│  misconception: 흐름 제어 → TCP (방향 역전)     │
└─────────────────────────────────────────────┘
```

> **핵심 설계 원칙 — 정보 격리(Information Isolation)**
> Student LLM은 `confirmed` / `partial` 상태 노드 ID와 사용자의 발화 히스토리만 받습니다.
> 체크리스트의 met/unmet 데이터, Reference KG 원문, missing 노드의 존재 자체는 절대 전달되지 않습니다.
> 이는 프롬프트 수준의 "모르는 척"이 아닌 **아키텍처 수준의 무지(無知) 보장**으로,
> 본 프로젝트의 가장 핵심적인 기술적 기여입니다.

### 전체 처리 흐름

```
[사전 준비] — 자료 업로드 시 1회 실행
PDF 업로드 → 텍스트 추출(NUL 바이트 정리) → 전체 문서 단위 슬라이딩 윈도우 청킹
→ 임베딩 생성 (배치 100개, 재시도 3회, pgvector 저장)
→ Reference KG 생성 (노드 후보 3회 추출 + consensus 병합 → 확정 노드 기반 상세 생성)
→ 동일 PDF 해시가 있으면 기존 Reference KG 재사용
→ User KG 초기화 (모든 노드가 missing 상태)

[실시간 학습] — 매 턴 반복
사용자 설명 입력
→ Evaluator LLM: 개념/관계 추출 + 체크리스트 met/unmet 판정
→ User KG 업데이트 (confirmed / partial / misconception)
→ RAG 기반 루브릭 채점 (4개 영역 × 0~3점, 총 12점)
→ 총점 10점 이상? Yes → 세션 종료 / No → Student LLM이 partial 기반 질문 1개 생성

[세션 종료]
세션 요약 + 점수 추이 제공
→ missing 노드 목록 + 체크리스트 met/unmet 결과 노출
→ 사용자가 다음 세션 주제 직접 선택
→ User KG 유지한 채로 다음 세션 시작
```

---

## 🗂️ 지식 그래프 (Knowledge Graph)

개념을 **노드(Node)**, 개념 간 관계를 **엣지(Edge)** 로 표현해 구조적 이해도를 추적합니다.

### 그래프 종류

| 종류 | 생성 시점 | 역할 | 변경 여부 |
|---|---|---|---|
| **Reference KG** | PDF 업로드 시 1회 | 정답 기준 그래프, Evaluator 비교 기준 | 고정 |
| **User KG** | 세션 진행 중 누적 | 사용자 이해도 추적 | 매 턴 갱신, 세션 간 유지 |

### 노드 상태 (4단계)

| 상태 | 의미 |
|---|---|
| `confirmed` | 모든 체크리스트 항목 met — 충분히 설명함 |
| `partial` | 일부 체크리스트만 met — 보완 필요 |
| `missing` | 아직 설명하지 않음 (Student LLM은 존재조차 모름) |
| `misconception` | 자료와 모순되는 설명 또는 관계 방향 역전 |

### 엣지 타입 — 9개 고정 RelationType

추상적 관계(`관련있다` 등)는 명시적으로 금지하며, 다음 9개 타입만 사용합니다.

| relation | 사용 조건 | 예시 |
|---|---|---|
| 포함한다 | A가 B를 내부 구성으로 포함 | TCP → 흐름 제어 |
| 구성요소이다 | A가 B의 부분 또는 구성요소 | 슬라이딩 윈도우 → 흐름 제어 |
| 종류이다 | A가 B의 한 종류 또는 유형 | TCP → 전송 계층 프로토콜 |
| 사용한다 | A가 B를 수단 또는 방법으로 활용 | 흐름 제어 → 슬라이딩 윈도우 |
| 전제한다 | A가 동작하려면 B가 먼저 필요 | 혼잡 제어 → ACK |
| 가능하게 한다 | A로 인해 B가 수행/달성됨 | 3-way handshake → 연결 수립 |
| 야기한다 | A가 B를 발생시킴 | 혼잡 → 패킷 손실 |
| 특성을 가진다 | A가 B라는 속성을 가짐 | TCP → 연결 지향 |
| 예시이다 | A가 B의 구체적 예시 | 슬라이딩 윈도우 → 흐름 제어 |

---

## 🛡️ Reference KG 품질 방어선

LLM 기반 KG 생성의 품질·일관성·환각 문제를 막기 위해 **3중 방어선**을 적용합니다.
이는 1회차 멘토링 피드백("KG가 의도에 맞게 올바르게 구성되었는지 판단하는 기준이 부재하다")을 반영한 설계입니다.

| 방어선 | 방식 | 효과 |
|---|---|---|
| **1. 인용 강제 (제약 프롬프트)** | 체크리스트 항목마다 RAG 청크 원문 `source_quote` 출력 강제, 인용 누락 항목은 자동 폐기 | LLM 임의 생성·환각 차단 |
| **2. 팀 교차 검토** | 생성된 KG를 팀에서 정성적으로 점검 (코드 외 영역) | 도메인 적합성 검증 |
| **3. 단계 분리형 Self-Consistency** | 노드 후보만 3회 추출한 뒤 과반수 consensus로 확정 노드 목록을 고정하고, 그 목록 안에서만 엣지·체크리스트 생성 | 노드명·엣지 endpoint 흔들림 완화 |

### 단계 분리형 Reference KG 생성

기존에는 LLM이 `노드 + 엣지 + 체크리스트 + 계층 구조`를 한 번에 생성했기 때문에,
같은 자료라도 노드명이나 엣지 endpoint가 달라질 수 있었습니다.
현재는 다음과 같이 생성 단계를 분리해 Reference KG의 일관성을 높였습니다.

```
PDF 청크 텍스트
→ 노드 후보만 3회 추출
→ 노드 ID 정규화 + 과반수 consensus로 최종 노드 목록 확정
→ 확정된 노드 목록 안에서만 체크리스트·엣지 생성
→ 목록 밖 노드/엣지 endpoint 자동 폐기
→ 후처리 + 루트 연결 + 정렬 저장
```

또한 PDF 파일의 SHA-256 해시를 저장해, 같은 PDF가 재업로드되면 기존 Reference KG를 재사용합니다.
따라서 동일 자료를 반복 업로드해도 기준 그래프가 다시 생성되며 달라지는 문제를 방지합니다.

### 추가 후처리

- **묶음 노드 체크리스트 정리**: 노드 A의 체크리스트가 다른 노드 B를 평가하는 메타 항목이면 자동 폐기 (한국어 단어 경계 매칭 + 안전장치 4종 적용)
- **자기 자신 엣지 폐기**: `source == target` 엣지는 의미 없으므로 제거
- **체크리스트 0개 노드 폐기**: 평가 불가능하므로 제거
- **직렬화 순서 고정**: 노드·엣지를 정렬해 JSON 저장 결과를 안정화

---

## 📊 평가 루브릭

매 턴마다 Evaluator LLM이 4개 영역을 0~3점으로 채점합니다 (총 12점).

| 영역 | 평가 기준 |
|---|---|
| **개념 커버리지** | Reference KG의 핵심 개념을 얼마나 다뤘는가 |
| **정확성** | 설명이 학습자료와 일치하는가 (RAG 비교) |
| **논리성** | 개념 간 관계 설명이 일관적인가 |
| **구체성** | 추상적 나열이 아닌 구체적 메커니즘으로 설명했는가 |

각 영역 점수와 met/unmet 체크리스트 결과는 **세션 종료 후에만** 사용자에게 노출됩니다.
세션 진행 중에는 Student LLM의 자연스러운 질문 흐름만 보이며, 능동적 인출(active recall)을 방해하지 않도록 설계했습니다.

---

## 🔁 세션 종료 조건

| 조건 | 기준 | 판단 주체 | 처리 |
|---|---|---|---|
| **정상 종료** | 총점 10점 이상 달성 | Evaluator LLM | 긍정 피드백 + 세션 요약 제공 |
| **반복 한계** | 동일 영역 3회 연속 2점 이하 | 시스템 | 자료 재학습 권장 안내 + 종료 |
| **턴 수 초과** | 총 대화 10턴 초과 | 시스템 | 세션 요약 + 종료 |
| **사용자 종료** | 직접 종료 요청 | 사용자 | 즉시 종료 + 현재까지 요약 |

> 반복 한계 3회 / 턴 수 10턴 기준은 사용자 테스트 후 조정 예정

---

## 🛠️ 기술 스택

| 분야 | 기술 |
|---|---|
| **Frontend** | React 19 + Vite 7 |
| **Backend** | FastAPI (Python 3.10+), SQLAlchemy |
| **Database** | PostgreSQL + pgvector |
| **AI** | OpenAI SDK v1.x (`gpt-5.4-mini-2026-03-17`, `text-embedding-3-small`) |
| **Knowledge Graph** | NetworkX |
| **PDF 처리** | PyPDF2 |
| **Containerization** | Docker Compose (`pgvector/pgvector:pg16`) |

---

## 📁 프로젝트 구조

```
.
├── backend/
│   ├── app/
│   │   ├── main.py                         # FastAPI 진입점 + CORS 설정
│   │   ├── config.py                       # 환경 설정
│   │   ├── database.py                     # SQLAlchemy 엔진 + 세션
│   │   ├── api/
│   │   │   ├── deps.py                     # DB 세션 의존성
│   │   │   └── v1/
│   │   │       ├── auth.py                 # 회원가입·로그인 API
│   │   │       ├── documents.py            # PDF 업로드 + 문서 목록·세션 이력 조회
│   │   │       ├── knowledge_graphs.py     # KG 조회 (Reference / User KG)
│   │   │       ├── sessions.py             # 세션 시작·턴 처리·종료 API
│   │   │       └── debug_kg.py             # KG 디버깅 엔드포인트 (debug 모드)
│   │   ├── core/
│   │   │   └── exceptions.py              # 커스텀 예외 클래스
│   │   ├── services/
│   │   │   ├── pdf_service.py             # PDF 텍스트 추출 + 슬라이딩 윈도우 청킹
│   │   │   ├── embedding_service.py       # 임베딩 생성 (배치 100, 재시도 3회)
│   │   │   ├── rag_service.py             # pgvector 코사인 유사도 검색
│   │   │   ├── kg_service.py              # KG 관리 + RelationType 정의
│   │   │   ├── reference_kg_generator.py  # 단계 분리형 Self-Consistency 기반 Reference KG 생성
│   │   │   ├── evaluator_llm.py           # Evaluator LLM 에이전트
│   │   │   ├── student_llm.py             # Student LLM 에이전트
│   │   │   └── session_service.py         # 2-에이전트 세션 오케스트레이터 + 세션 자동 저장
│   │   ├── models/
│   │   │   ├── document.py                # Document SQLAlchemy 모델 + PDF 해시 캐시 키
│   │   │   ├── chunk.py                   # Chunk + pgvector 임베딩 모델
│   │   │   ├── knowledge_graph.py         # KnowledgeGraph 모델 (reference/user KG)
│   │   │   ├── session_record.py          # SessionRecord 모델 (세션 이력)
│   │   │   └── user.py                    # User 모델 (회원가입·로그인)
│   │   └── schemas/
│   │       └── document.py                # Pydantic 스키마
│   ├── alembic/                           # DB 마이그레이션 (autogenerate 활성화)
│   └── tests/
│       ├── test_pdf_service.py
│       ├── test_kg_service.py
│       ├── test_reference_kg_generation.py
│       └── test_reference_kg_generator_staged.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx                        # 라우팅 설정
│   │   ├── main.jsx
│   │   ├── api.js                         # 공통 API 유틸리티 + KG 레이아웃 함수
│   │   ├── context/
│   │   │   └── AuthContext.jsx            # 인증 상태 관리 (백엔드 연동)
│   │   ├── components/
│   │   │   ├── Navbar.jsx                 # 상단 네비게이션
│   │   │   ├── KnowledgeGraph.jsx         # KG 시각화 (centered subtree 레이아웃)
│   │   │   ├── DonutChart.jsx             # 커버리지 도넛 차트
│   │   │   ├── LoginModal.jsx             # 로그인 모달
│   │   │   └── ...                        # Button, Header, Footer, Main
│   │   └── pages/
│   │       ├── MainPage.jsx               # 랜딩 페이지
│   │       ├── UploadAnalysis.jsx         # PDF 업로드 + 실제 KG 시각화 (API 연동)
│   │       ├── TeacherMode.jsx            # 페인만 기법 채팅 — sessions API 연동
│   │       ├── StudentMode.jsx            # AI 튜터 채팅 (목 데이터, 미연동)
│   │       ├── SessionReport.jsx          # 세션 리포트 — 실데이터 + KG 비교 시각화
│   │       ├── MyArchive.jsx              # 학습 기록 아카이브 — documents/sessions API 연동
│   │       └── Register.jsx              # 회원가입 (API 연동)
├── docker-compose.yml                     # PostgreSQL + pgvector DB
└── Readme.md
```

---

## 🚀 시작하기

### 사전 요구사항

- Docker & Docker Compose
- Python 3.10+
- Node.js 18+
- OpenAI API Key

### 실행

```bash
# 저장소 클론
git clone <REPO_URL>
cd capstone

# 환경 변수 설정
cp .env.example .env
# .env에 OPENAI_API_KEY 입력

# DB 컨테이너 실행
docker compose up -d

# 백엔드 실행
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 프론트엔드 실행
cd frontend
npm install
npm run dev
```

서비스가 시작되면 다음 주소로 접속할 수 있습니다.

- 프론트엔드: `http://localhost:5173`
- 백엔드 API 문서 (Swagger): `http://localhost:8000/docs`

---

## 📌 현재 개발 상태

### ✅ 완료

**백엔드**
- [x] PDF 처리 파이프라인 (PyPDF2 추출 → NUL 바이트 정리 → 슬라이딩 윈도우 청킹)
- [x] 벡터화 파이프라인 (임베딩 배치 100개 + 재시도 3회 → pgvector 저장)
- [x] RAG 서비스 (`rag_service.py` — pgvector 코사인 유사도 검색)
- [x] Knowledge Graph 서비스 (`kg_service.py`)
  - [x] RelationType 9개 고정 타입셋
  - [x] `EdgeStatus.MISCONCEPTION` (관계 방향 역전·잘못된 타입 감지)
  - [x] 체크리스트 met/unmet 데이터는 세션 종료 시점에만 노출
- [x] Reference KG 생성기 (`reference_kg_generator.py`)
  - [x] 방어선 1 — `source_quote` 인용 강제
  - [x] 방어선 3 — 노드 후보 3회 호출 + consensus 병합
  - [x] 확정 노드 목록 기반 엣지·체크리스트 생성
  - [x] 목록 밖 노드/엣지 endpoint 자동 폐기
  - [x] 묶음 노드 체크리스트 후처리 (한국어 단어 경계 매칭)
  - [x] 자기 자신 엣지 폐기
  - [x] PDF SHA-256 해시 기반 Reference KG 캐시
- [x] Evaluator LLM (`evaluator_llm.py` — 루브릭 채점 + User KG 업데이트)
- [x] Student LLM (`student_llm.py` — 정보 격리 기반 질문 생성)
- [x] 2-에이전트 세션 오케스트레이터 (`session_service.py`)
- [x] REST API 엔드포인트
  - [x] `GET /api/v1/documents` — 문서 목록 조회
  - [x] `POST /api/v1/documents/upload` — PDF 업로드 + KG 생성
  - [x] `GET /api/v1/documents/{id}` — 문서 상태 조회
  - [x] `GET /api/v1/documents/{id}/sessions` — 문서별 세션 이력 조회
  - [x] `GET /api/v1/knowledge-graphs/{id}` / `/reference` / `/user` — KG 조회
  - [x] `POST /api/v1/sessions/start` / `turn` / `end` — 세션 관리
  - [x] `POST /api/v1/auth/register` / `login` — 회원가입·로그인
- [x] DB 모델 및 Alembic 마이그레이션 (autogenerate 활성화)
  - [x] `Document`, `Chunk`, `KnowledgeGraph`, `SessionRecord`, `User` 모델
- [x] 세션 종료 시 `SessionRecord` 자동 저장 (점수·커버리지·오개념·종료 사유)
- [x] 비밀번호 bcrypt 해싱 (`passlib` 의존성 제거, `bcrypt` 직접 사용)

**프론트엔드**
- [x] 전체 페이지 UI 구현 (MainPage, UploadAnalysis, TeacherMode, StudentMode, SessionReport, MyArchive, Register)
- [x] KG 시각화 컴포넌트 (`KnowledgeGraph.jsx`) — centered subtree 트리 레이아웃, 긴 한글 레이블 줄바꿈
- [x] 커버리지 도넛 차트 (`DonutChart.jsx`)
- [x] 인증 컨텍스트 (`AuthContext.jsx`)
- [x] API 유틸리티 (`api.js`) — 공통 fetch 래퍼, KG 레이아웃/엣지 변환, 라벨 폭 기반 노드 간격 계산

**프론트엔드 ↔ 백엔드 연동**
- [x] UploadAnalysis — 실제 PDF 업로드 + Reference KG 시각화
- [x] TeacherMode — `sessions/start·turn·end` API 연동, 실시간 오개념 표시
- [x] SessionReport — 세션 결과 실데이터 표시, User KG BEFORE/AFTER 비교, 노드별 체크리스트
- [x] MyArchive — 문서 목록·세션 이력 실데이터 연동
- [x] Register / LoginModal — 백엔드 회원가입·로그인 API 연동

### 🚧 진행 중 / 예정

- [ ] StudentMode 백엔드 연동 (RAG 기반 Q&A API 미구현)
- [ ] Evaluator LLM 루브릭 일관성 검증 (저품질/중간/고품질 샘플로 5회 반복 편차 ±1점 확인)
- [ ] 사용자별 문서 격리 (현재 모든 사용자가 동일 문서 목록 공유)

---

## 👥 팀 구성

세종대학교 캡스톤디자인 팀 프로젝트 (2026) — **팀명: 양말**

| 역할 | 이름 |
|---|---|
| 팀장 | 이현규 |
| 팀원 | 김가현 |
| 팀원 | 조영선 |
| 팀원 | 김세람 |

### 멘토링

- **담당교수**: 세종대학교 김세원 교수
- **기업 멘토**: LG전자 CTO부문 C&M표준연구소 6G Radio표준Task 배덕현 선임연구원

---

## 📄 라이선스

MIT License
