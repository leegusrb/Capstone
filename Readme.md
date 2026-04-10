# 📚 FeynAI — 페인만 기법 기반 자기주도학습 서비스

> **"AI에게 설명해보세요. 진짜로 이해했는지 확인할 수 있습니다."**

학습자가 AI 학생 에이전트에게 개념을 설명하면, AI가 사용자의 누적 설명을 학습자료 기반 지식 그래프로 추적하고 평가하며 추가 질문을 이어가는 **페인만 기법 기반 자기주도학습 서비스**입니다.

---

## ✨ 핵심 아이디어

기존 AI 학습 도구는 **"질문 → 답변"** 구조입니다. 학습자는 수동적으로 정보를 받아들입니다.

이 서비스는 반대입니다.

> **학습자가 AI에게 설명합니다.**

AI는 답을 주는 튜터가 아닌, **해당 주제에 대해 진짜로 아무것도 모르는 학생 에이전트**입니다.  
"모르는 척"이 아닙니다. 사용자가 설명한 내용만을 지식 그래프로 누적해 기억하며, 설명받지 않은 개념은 **아키텍처 수준에서 접근 자체가 차단**됩니다.

---

## 🆚 기존 서비스와의 차이

| 구분 | 기존 서비스 | 이 서비스 |
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
│  (학생 에이전트)   │  │   (평가자 에이전트)      │
│                 │  │                      │
│ • 사전 지식 없음    │  │ • RAG 학습자료 보유    │
│ • confirmed /   │  │ • 루브릭 4개 영역       │
│   partial만     │  │   채점                │
│   참조 가능       │  │ • User KG 업데이트     │
│ • missing 노드   │  │ • 세션 종료 판단        │
│   접근 불가       │  │ • 백그라운드 처리        │
│ • 사용자에게       │  │                      │
│   직접 노출       │  │                      │
└────────┬────────┘  └──────────┬───────────┘
         │                      │
         │         User KG 공유  │
         ▼                      ▼
┌─────────────────────────────────────────────┐
│     Knowledge Graph (User KG) — 세션 간 누적   │
│                                              │
│  confirmed:     TCP → 연결 지향 (정확)          │
│  partial:       TCP → 흐름 제어 (관계 모호)     │
│  missing:       TCP → 혼잡 제어               │
│  misconception: (오개념 기록)                 │
└─────────────────────────────────────────────┘
```

### 전체 처리 흐름

```
[사전 준비] — 자료 업로드 시 1회 실행
PDF 업로드 → 텍스트 추출 → 청크 분할
→ 임베딩 생성 (pgvector 저장)
→ Reference KG 생성 (핵심 개념 + 관계 추출)
→ User KG 초기화 (빈 상태)

[실시간 학습] — 매 턴 반복
사용자 설명 입력
→ Evaluator LLM: 개념/관계 추출 → User KG 업데이트
→ Reference KG ↔ User KG 비교 → 상태 판정
→ RAG 기반 루브릭 채점 (4개 영역 × 0~3점)
→ 총점 10점 이상? Yes → 세션 종료 / No → 추가 질문 생성

[세션 종료]
세션 요약 + 점수 추이 제공
→ missing 노드 목록 노출
→ 사용자가 다음 세션 주제 직접 선택
→ User KG 유지한 채로 다음 세션 시작
```

---

## 🗂️ 지식 그래프 (Knowledge Graph)

개념을 **노드(Node)**, 개념 간 관계를 **엣지(Edge)**로 표현해 구조적 이해도를 추적합니다.

```
[TCP] ──포함한다──▶ [흐름 제어]
  │
  └──포함한다──▶ [혼잡 제어]
                       │
            ──작동 방식──▶ [슬라이딩 윈도우]
```

### 노드/엣지 상태

| 상태 | 의미 |
|---|---|
| `confirmed` | 사용자가 정확하게 설명한 개념 및 관계 |
| `partial` | 언급은 됐지만 설명이 불완전하거나 관계가 모호함 |
| `missing` | Reference KG에 존재하지만 아직 설명되지 않음 |
| `misconception` | Reference KG에 없는 내용을 사용자가 잘못 설명한 오개념 |

### Reference KG vs User KG

| 구분 | Reference KG | User KG |
|---|---|---|
| **생성 시점** | PDF 업로드 시 1회 | 매 턴 누적 업데이트 |
| **내용** | 학습자료에서 추출한 정답 기준 그래프 | 사용자 설명에서 추출한 동적 그래프 |
| **변경 여부** | 고정 (변하지 않음) | 세션 간에도 누적 유지 |
| **역할** | 평가 비교 기준 | 현재 이해도 상태 |

---

## 📊 평가 루브릭

Evaluator LLM이 사용자의 설명을 4개 영역 × 0~3점 (총 12점 만점)으로 채점합니다.

| 영역 | 0점 | 1점 | 2점 | 3점 |
|---|---|---|---|---|
| **핵심 개념 포함** | 핵심 개념 거의 없음 | 일부만 포함 | 대부분 포함 | 빠짐없이 포함 |
| **정확성** | 핵심 오류 존재 | 모호한 부분 많음 | 전반적으로 정확, 세부 부족 | 핵심·세부 모두 정확 |
| **논리성** | 문장 나열 수준 | 부분적 연결만 존재 | 흐름은 있으나 일부 비약 | 원인–과정–결과 자연스럽게 연결 |
| **구체성** | 추상적 표현만 있음 | 약간의 구체화만 있음 | 구체적 표현 포함 | 예시·적용 상황까지 제시 |

**총점 10점 이상 → 세션 종료 / 9점 이하 → 추가 질문 생성**

> 10점 기준은 현재 가설 수치이며, 사용자 테스트 후 조정 예정입니다.

### Evaluator LLM 응답 스키마

```json
{
  "scores": {
    "concept": 2,
    "accuracy": 1,
    "logic": 3,
    "specificity": 0
  },
  "total": 6,
  "is_sufficient": false,
  "updated_user_kg": {
    "nodes": [
      { "id": "TCP", "status": "confirmed" },
      { "id": "흐름 제어", "status": "partial" },
      { "id": "혼잡 제어", "status": "missing" }
    ],
    "edges": [
      { "source": "TCP", "relation": "포함", "target": "흐름 제어", "status": "partial" },
      { "source": "TCP", "relation": "포함", "target": "혼잡 제어", "status": "missing" }
    ]
  },
  "misconceptions": [],
  "weak_areas": ["specificity", "accuracy"]
}
```

---

## 🔁 세션 종료 조건

| 조건 | 기준 | 처리 |
|---|---|---|
| **정상 종료** | 총점 10점 이상 | 긍정 피드백 + 세션 요약 |
| **반복 한계** | 동일 영역 3회 연속 2점 이하 | 자료 재학습 권장 + 종료 |
| **턴 수 초과** | 총 10턴 초과 | 세션 요약 + 종료 |
| **사용자 종료** | 직접 종료 요청 | 즉시 종료 + 현재까지 요약 |

---

## 🛠️ 기술 스택

| 분야 | 기술 |
|---|---|
| **Frontend** | React + Vite |
| **Backend** | FastAPI (Python 3.10+) |
| **Database** | PostgreSQL + pgvector |
| **AI** | OpenAI API (GPT, text-embedding-3-small) |
| **Knowledge Graph** | NetworkX (Python) |
| **Containerization** | Docker Compose |

---

## 📁 프로젝트 구조

```
.
├── backend/
│   ├── main.py                 # FastAPI 진입점
│   ├── routers/                # API 라우터
│   ├── services/
│   │   ├── kg_service.py       # Knowledge Graph 관리
│   │   ├── rag_service.py      # pgvector 유사도 검색
│   │   ├── student_llm.py      # Student LLM 에이전트
│   │   └── evaluator_llm.py    # Evaluator LLM 에이전트
│   └── models/                 # Pydantic / DB 모델
├── frontend/
│   ├── src/
│   │   ├── components/         # React 컴포넌트
│   │   └── pages/              # 페이지 구성
│   └── vite.config.js
└── docker-compose.yml
```

---

## 🚀 시작하기

### 사전 요구사항

- Docker & Docker Compose
- OpenAI API Key

### 실행

```bash
# 저장소 클론
git clone https://github.com/your-org/feynai.git
cd feynai

# 환경 변수 설정
cp .env.example .env
# .env에 OPENAI_API_KEY 입력

# 서비스 실행
docker compose up --build
```

서비스가 시작되면 `http://localhost:5173` 에서 접속할 수 있습니다.

---

## 📌 현재 개발 상태

- [x] 벡터화 파이프라인 (PDF → 임베딩 → pgvector)
- [x] Knowledge Graph 서비스 (`kg_service.py`)
- [x] 2-에이전트 아키텍처 설계 확정
- [ ] RAG 서비스 구현 (`rag_service.py`)
- [ ] Evaluator LLM 프롬프트 설계 및 JSON 스키마 확정
- [ ] 2-에이전트 세션 통합
- [ ] 프론트엔드 채팅 인터페이스
- [ ] 세션 요약 및 KG 커버리지 시각화

---

## 👥 팀 구성

세종대학교 캡스톤디자인 팀 프로젝트 (2026)

| 역할 | 담당 |
|---|---|
| AI / LLM 설계 | - |
| 백엔드 개발 | - |
| 프론트엔드 개발 | - |

---

## 📄 라이선스

MIT License