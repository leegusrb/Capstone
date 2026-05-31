"""
services/reference_kg_generator.py  (v3.2 패치 적용판)
------------------------------------------------------
v2 → v3 변경점:
  - [PATCH v3-1] 묶음 노드 체크리스트 작성 규칙 (2-7) 신설 (프롬프트)
  - [PATCH v3-2] 시간/순서 시리즈 분리 예시 강화 (1-4-b)
                 → 이슈 4 (시대 노드 누락) 해결
  - [PATCH v3-3] 엣지 방향 일관성 규칙 (3-5) + 후처리 함수
                 → 이슈 3 (엣지 방향 모순) 해결

v3 → v3.1 추가 변경점:
  - [PATCH v3.1-1] 묶음 노드 체크리스트 결정론적 후처리
                   → 이슈 1, 2 (프롬프트만으로 안 잡힘) 해결
                   _filter_meta_checklist_items() 신설
  - [PATCH v3.1-2] 자기 자신 엣지 폐기 후처리

v3.1 → v3.2 회귀 수정:
  - [PATCH v3.2-1] _filter_meta_checklist_items() 부분 문자열 매칭 회귀 수정
                   → 단어 경계 매칭, 3자 미만 ID 제외, 4가지 안전장치 추가

v3.2 → v4 (이후):
  - [PATCH v4-5] 루트 직접 자식 클러스터링
                 → 루트 자식이 임계값(기본 6개) 초과 시 LLM으로 중간 계층 삽입

기획서 §4-1 Reference KG 추출 규칙을 LLM 프롬프트에 명시적으로 주입하며,
다음 2가지 자동 품질 방어선을 적용한다 (방어선 2 팀 교차 검토는 코드 외 영역).

  방어선 1 — 제약 프롬프트 + 인용 강제
    체크리스트 항목마다 RAG 청크 원문 인용(source_quote)을 함께 출력하도록 강제.
    인용 누락 항목은 reject.

  방어선 3 — Self-Consistency (consensus 정책)
    동일 청크에 대해 N회 반복 호출 후 다수결로 병합.
    노드 ID 정규화로 호출 간 표기 차이를 흡수.

본 모듈은 PDF 업로드 시점에 1회만 호출되며, 결과는 KnowledgeGraph 테이블의
reference_kg 컬럼에 저장된다.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx
from openai import OpenAI

from app.config import settings
from app.services.kg_service import RelationType

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=settings.openai_api_key)

_ALLOWED_RELATIONS = {r.value for r in RelationType}
KG_DEFAULT_MODEL = "gpt-5.4-mini-2026-03-17"
KG_HIGH_QUALITY_MODEL = "gpt-5.4-2026-03-05"


# ──────────────────────────────────────────────
# 1. relation 타입 가이드 (프롬프트 주입용)
# ──────────────────────────────────────────────

_RELATION_TYPE_GUIDE = """\
| relation       | 사용 조건                              | 예시                          |
|----------------|---------------------------------------|------------------------------|
| 포함한다       | A가 B를 내부 구성으로 포함            | TCP → 흐름 제어               |
| 구성요소이다   | A가 B의 부분 또는 구성요소            | 슬라이딩 윈도우 → 흐름 제어    |
| 종류이다       | A가 B의 한 종류 또는 유형             | TCP → 전송 계층 프로토콜       |
| 사용한다       | A가 B를 수단 또는 방법으로 활용       | 흐름 제어 → 슬라이딩 윈도우    |
| 전제한다       | A가 동작하려면 B가 먼저 필요          | 혼잡 제어 → ACK               |
| 가능하게 한다  | A로 인해 B가 수행되거나 달성됨        | 3-way handshake → 연결 수립   |
| 야기한다       | A가 B를 발생시키거나 원인이 됨        | 혼잡 → 패킷 손실               |
| 특성을 가진다  | A가 B라는 속성 또는 특징을 가짐       | TCP → 연결 지향                |
| 예시이다       | A가 B의 구체적 예시                   | 슬라이딩 윈도우 → 흐름 제어    |
"""


# ──────────────────────────────────────────────
# 2. Reference KG 추출 프롬프트
# ──────────────────────────────────────────────

_REFERENCE_KG_EXTRACTION_PROMPT = """\
당신은 학습 자료에서 핵심 개념과 개념 간 관계, 그리고 각 개념의 핵심 속성을 추출하는 전문가입니다.

학습 자료 텍스트를 분석해 (1) 노드, (2) 노드별 체크리스트, (3) 엣지를 모두 포함한 지식 그래프를 생성해주세요.

이 작업의 목적은 학생이 자료 내용을 정확히 설명했는지 평가하는 것입니다.
따라서 자료에 등장하는 핵심 개념을 빠짐없이 추출해야 하며, 누락이 있으면 평가 기준 자체가 부실해집니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1] 노드 추출 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(1-1) 단일 개념 원칙
  - 하나의 노드는 반드시 하나의 단일 개념 또는 용어만 나타냅니다.
  - 복합 개념("A와 B")은 반드시 별도 노드로 분리하세요.
  - 잘못된 예: 노드 = "흐름 제어와 혼잡 제어"
  - 올바른 예: 노드 = "흐름 제어", 노드 = "혼잡 제어"

(1-2) 하위 메커니즘 분리
  - 특정 개념의 구현 방식·구성 요소·하위 메커니즘이 독립적으로 설명 가능한
    경우 별도 노드로 추출합니다.
  - 예: "흐름 제어"의 하위 메커니즘 "슬라이딩 윈도우", "버퍼"는 별도 노드.

(1-3) 노드 수 목표
  - 자료에 등장하는 핵심 개념을 빠짐없이 추출하되,
    일반적인 학습 자료는 15~25개를 목표로 하세요.
    매우 풍부한 자료도 30개를 초과하지 마세요.
  - 개념을 인위적으로 묶어 노드 수를 줄이지 마세요.
  - 자료에서 한 번만 스쳐 지나가는 사소한 용어, 핵심 역할이 없는
    부수적 표현은 노드로 만들지 않습니다.

(1-4) 범주 묶음 금지 — 매우 중요
  - 자료에서 여러 항목이 별도로 설명되는 경우, 그 항목들을 묶는 범주명을
    단일 노드로 만들면 안 됩니다. 각 항목을 모두 별도 노드로 분리하세요.

  (1-4-a) 분류 체계의 분리
    판단 기준: 자료에서 한 항목당 1문장 이상 별도 항목으로 다루어진다면
              별도 노드로 분리. 자료에서 단순히 나열만 된 항목은 묶음 노드의
              체크리스트로 처리.

  (1-4-b) 시간/순서 시리즈의 분리 — 매우 중요
    자료에서 여러 시대·단계·세대가 차례로 설명되면 모든 단위를 빠짐없이
    별도 노드로 분리하세요. 일부만 분리하고 나머지를 누락하면 안 됩니다.
    자료에 등장하는 모든 시대/단계 노드 수를 먼저 확인한 뒤 누락이 없는지 점검하세요.

(1-5) 정리/요약 섹션 의존 금지 — 매우 중요
  - 자료에 "정리", "요약", "핵심 정리", "복습" 같은 섹션이 있어도
    그 섹션만 보고 노드를 만들지 마세요.
  - 자료의 모든 페이지·섹션·단락을 검토해 본문 전체에서 등장하는 핵심 개념을
    추출하세요.

(1-6) 과도한 세분화 금지
  - 자료에서 핵심 역할을 하지 않는 지나치게 세부적인 용어는 상위 개념 노드에 포함하거나 제외합니다.
  - 개념의 별칭·동의어(예: "경량 프로세스"는 스레드의 별칭)는 별도 노드로
    만들지 말고 해당 개념의 체크리스트에서 언급하세요.
  - 두 개념 사이의 "관계" 자체는 절대 노드로 만들지 마세요. — 매우 중요
    "A와 B의 관계", "A와 B의 차이", "A와 B의 비교" 형태의 노드는 금지합니다.
    잘못된 예: 노드 = "스레드와 프로세스의 관계"
    올바른 예: 노드 = "스레드" (체크리스트: "프로세스와 달리 같은 프로세스 내 메모리를 공유함을 명시")
              + 엣지로 두 노드 사이의 관계를 표현

(1-7) 열거형 속성·동작은 상위 노드 체크리스트로 처리 — 매우 중요
  어떤 개념의 구성 필드, 상태 목록, 조건 목록, 세부 동작이 자료에서
  단순히 열거되는 경우, 각 항목을 별도 노드로 만들지 말고
  해당 개념 노드의 체크리스트 항목으로 처리하세요.

  판단 기준: 항목이 자료에서 독립적인 섹션·단락으로 별도 설명되는가?
    YES → 별도 노드
    NO  → 상위 노드 체크리스트 항목

  잘못된 예 (열거 항목을 별도 노드화):
    노드 = "프로세스 ID", 노드 = "레지스터 값", 노드 = "프로그램 카운터"
    → PCB가 포함하는 필드를 나열한 것. "PCB" 노드 체크리스트로 처리.
    노드 = "생성", 노드 = "준비", 노드 = "실행", 노드 = "대기", 노드 = "종료"
    → 프로세스 상태 5가지를 나열한 것.
       "프로세스 상태 전이" 노드의 체크리스트로 처리.
    노드 = "상호 배제", 노드 = "진행", 노드 = "유한 대기"
    → 임계 구역의 3가지 조건을 나열한 것. "임계 구역" 체크리스트로 처리.
    노드 = "획득", 노드 = "해제"
    → 뮤텍스의 세부 동작. "뮤텍스" 체크리스트로 처리.
    노드 = "상호 배제", 노드 = "점유 대기", 노드 = "비선점", 노드 = "원형 대기"
    → 교착 상태의 4가지 조건을 나열한 것. "교착 상태의 4가지 조건" 체크리스트로 처리.
    노드 = "예방", 노드 = "회피", 노드 = "탐지 및 복구", 노드 = "무시"
    → 교착 상태 처리 전략의 종류. "교착 상태 처리 전략" 체크리스트로 처리.

  올바른 예:
    노드 = "PCB"
      체크리스트: "PID·프로세스 상태·PC·레지스터·스케줄링 정보 등을 포함함을 명시"
    노드 = "프로세스 상태 전이"
      체크리스트: "생성→준비→실행→대기→종료 5단계가 있음을 명시"
    노드 = "임계 구역"
      체크리스트: "상호 배제·진행·유한 대기 세 조건을 만족해야 함을 명시"
    노드 = "뮤텍스"
      체크리스트: "락 획득(acquire)/해제(release)로 임계 구역을 보호함을 명시"
    노드 = "교착 상태의 4가지 조건"
      체크리스트: "상호 배제·점유 대기·비선점·원형 대기 4가지가 동시 성립 시 발생함을 명시"
    노드 = "교착 상태 처리 전략"
      체크리스트: "예방·회피·탐지 및 복구·무시의 4가지 전략이 있음을 명시"

  예외: 열거된 항목이라도 자료에서 각 항목에 대해 독립된 섹션·단락이 있으면
        별도 노드로 분리하세요.
        예: 이진 세마포어, 카운팅 세마포어는 각각 별도 설명이 있으므로 별도 노드.

(1-8) 주요 섹션 노드 보장 — 매우 중요
  자료가 여러 챕터·섹션으로 구성된 경우, 각 주요 섹션의 핵심 개념을
  반드시 상위 노드로 포함하세요. 이 노드들이 하위 개념들의 부모 역할을
  해야 계층 구조가 형성됩니다.

  잘못된 예:
    "4. 프로세스 동기화" 챕터 아래 경쟁 조건·임계 구역·뮤텍스·세마포어를
    노드로 만들었으나 "프로세스 동기화" 노드를 만들지 않음

  올바른 예:
    노드 = "프로세스 동기화" (체크리스트: 동기화의 필요성·목표를 명시)
    + 하위에 경쟁 조건·임계 구역·뮤텍스·세마포어를 연결하는 엣지 추가

  주의: 섹션 이름이 곧 핵심 개념일 때만 노드로 만드세요.
        "개요", "예시 코드", "정리" 같은 섹션 제목은 노드 대상이 아닙니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2] 노드별 체크리스트 추출 규칙 — 매우 중요
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

각 노드는 사용자가 해당 개념을 "정확하게 설명했다"고 판정하기 위한
체크리스트를 가져야 합니다.

(2-1) 출처 강제 — 각 체크리스트 항목마다 source_quote 필수
  - 각 항목 옆에 그 항목의 근거가 된 학습 자료의 원문 인용을 함께 출력합니다.
  - source_quote는 학습 자료 본문에 등장한 설명 문장이어야 합니다.
  - 자료의 목차·섹션 제목은 인용으로 사용하지 마세요. 실제 설명 문장을 인용하세요.
  - source_quote가 빈 문자열이거나 누락된 항목은 평가 시스템에서 reject됩니다.

(2-2) 항목 수 제한
  - 노드당 2~4개 작성. 5개 이상 만들지 마세요.
  - 자료에서 해당 개념에 대한 사실을 1개밖에 찾을 수 없다면 독립 노드로
    만들지 말고 상위 노드의 체크리스트 항목으로만 다루세요.

(2-3) 단일 속성 원칙
  - 한 항목은 반드시 하나의 사실만 담아야 합니다. Y/N 판정이 가능한 단위여야 합니다.
  - 잘못된 예: "TCP의 특성과 동작 방식"  ← 포괄적, Y/N 판정 불가
  - 올바른 예: "TCP가 연결 지향임을 명시"  ← 단일 속성

(2-4) 자료 외 추론 금지
  - 학습 자료에 명시되지 않은 내용은 체크리스트에 포함할 수 없습니다.

(2-5) 표현 형식 통일
  - 항목 끝은 다음 동사 중 하나로 종결합니다:
    "~를 명시", "~를 언급", "~의 역할 설명", "~의 이유 설명", "~의 동작 설명"

(2-6) 노드 범위와 체크리스트 범위 일치 — 매우 중요
  - 체크리스트는 반드시 해당 노드 자체의 정의·속성·특징만 담아야 합니다.
  - 노드의 일부 측면에만 해당하는 내용은 별도 노드로 분리해야 합니다.

(2-7) 묶음 노드의 체크리스트 작성 규칙 — 매우 중요
  - 하위 항목들이 별도 노드로 분리된 상위(묶음) 노드의 체크리스트에는
    하위 노드의 내용을 메타로 묻는 항목을 절대 넣지 마세요. (이중 평가)

  허용:
    1. 묶음 자체의 분류 체계·정의·범주에 대한 사실
    2. 하위 항목들에 공통으로 적용되는 일반 사실
    3. 묶음 자체에 대한 자료의 직접적 진술

  금지:
    - "X(하위 노드 이름)의 특징을 설명" / "X를 명시"
    - 하위 노드의 체크리스트와 동일하거나 유사한 내용

  주의: 묶음 노드는 체크리스트 항목 수가 1개여도 허용됩니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[3] 엣지 추출 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(3-1) 고정 relation 타입 사용
  - relation은 반드시 아래 9개 중 하나만 사용합니다. 임의의 동사구 금지.

""" + _RELATION_TYPE_GUIDE + """

(3-2) 방향성 명시
  - 모든 엣지는 source → target 방향을 명확히 지정합니다.

(3-3) 엣지의 source/target은 반드시 nodes 배열에 정의된 노드 id여야 합니다.

(3-4) 분리된 노드들 간 관계 명시
  - (1-4)에 따라 범주를 분리한 경우, 분리된 항목들 간의 관계를 엣지로 표현하세요.

(3-5) 엣지 방향 일관성 — 매우 중요
  - 같은 두 노드 사이에 양방향(A→B와 B→A)으로 엣지를 만들지 마세요.
  - 권장 패턴:
    - "A는 B를 포함한다" → A -[포함한다]-> B
    - "B는 A의 일부이다" → B -[구성요소이다]-> A
    (둘 중 하나만 선택)

(3-6) 상위-하위 계층 연결 완성 — 매우 중요
  (1-8)에 따라 주요 섹션 노드를 만든 경우, 그 섹션에 속하는 모든
  하위 개념 노드를 빠짐없이 엣지로 연결하세요.

  올바른 예:
    프로세스 동기화 -[포함한다]-> 경쟁 조건
    프로세스 동기화 -[포함한다]-> 임계 구역
    프로세스 동기화 -[포함한다]-> 뮤텍스
    프로세스 동기화 -[포함한다]-> 세마포어

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[4] 출력 형식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

반드시 아래 JSON 형식만 반환하세요. 설명, 마크다운 펜스, 주석 없이 순수 JSON만.

{
  "nodes": [
    {
      "id": "TCP",
      "checklist": [
        {
          "item": "연결 지향 방식임을 명시",
          "source_quote": "TCP는 연결 지향 프로토콜이다."
        },
        {
          "item": "3-way handshake로 연결을 수립함을 명시",
          "source_quote": "TCP는 SYN, SYN-ACK, ACK의 3단계 과정을 통해 연결을 수립한다."
        }
      ]
    }
  ],
  "edges": [
    {"source": "TCP", "relation": "포함한다", "target": "흐름 제어"}
  ]
}

학습 자료:
"""

_NODE_CANDIDATE_EXTRACTION_PROMPT = """\
당신은 학습 자료에서 Reference Knowledge Graph의 노드 후보만 추출하는 전문가입니다.

학습 자료 텍스트를 분석해 핵심 개념 노드 후보를 추출해주세요.
이 단계에서는 엣지와 체크리스트를 만들지 않습니다.

규칙:
1. 하나의 노드는 반드시 하나의 단일 개념 또는 용어만 나타냅니다.
2. "A와 B의 관계", "A와 B의 차이", 별칭·동의어는 노드로 만들지 않습니다.
3. 자료에서 독립적으로 설명되는 핵심 개념만 노드로 만듭니다.
4. 단순 열거 항목은 별도 노드로 만들지 말고 상위 개념의 속성으로 봅니다.
5. 일반적인 학습 자료는 15~25개를 목표로 하며, 30개를 초과하지 않습니다.
6. 각 노드는 근거가 된 학습 자료 원문 인용(source_quote)을 반드시 포함합니다.
7. source_quote는 빈 문자열이면 안 되며, 자료 본문의 실제 설명 문장이어야 합니다.

반드시 아래 JSON 형식만 반환하세요. 설명, 마크다운 펜스, 주석 없이 순수 JSON만.

{
  "nodes": [
    {"id": "TCP", "source_quote": "TCP는 연결 지향 프로토콜이다."}
  ]
}

학습 자료:
"""

_FIXED_NODE_DETAIL_INSTRUCTIONS = """\

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[0] 확정 노드 목록 — 최우선 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

아래 노드 목록은 이미 확정된 Reference KG 노드입니다.
nodes 배열에는 반드시 이 목록의 id만 사용하세요.
edges의 source/target도 반드시 이 목록의 id만 사용하세요.
목록에 없는 새 노드를 추가하거나, 목록의 id를 다른 표현으로 바꾸면 안 됩니다.

확정 노드 목록:
{node_list}

"""


# ──────────────────────────────────────────────
# 3. 데이터 클래스
# ──────────────────────────────────────────────

@dataclass
class NodeCandidate:
    """노드 후보. source_quote는 후보 채택 근거 확인용 원문 인용."""
    id: str
    source_quote: str


@dataclass
class ChecklistItem:
    """노드의 체크리스트 항목 1개. source_quote는 자료에서 그대로 인용된 문장."""
    item: str
    source_quote: str


@dataclass
class NodeWithChecklist:
    """체크리스트가 부여된 KG 노드."""
    id: str
    checklist: list[ChecklistItem] = field(default_factory=list)


@dataclass
class EdgeData:
    """KG 엣지. relation은 9개 고정 타입 중 하나."""
    source: str
    relation: str
    target: str


@dataclass
class ExtractionResult:
    """단일 LLM 호출의 추출 결과."""
    nodes: list[NodeWithChecklist]
    edges: list[EdgeData]


# ──────────────────────────────────────────────
# 4. 노드 ID 정규화 (호출 간 표기 차이 흡수)
# ──────────────────────────────────────────────

def _normalize_node_id(node_id: str) -> str:
    """
    노드 ID를 정규화하여 호출 간 표기 차이를 흡수한다.

    예시:
      "녹차(綠茶)"             → "녹차"
      "신농씨(炎帝 神農氏)"    → "신농씨"
      "  TCP   "               → "TCP"

    한자/한자병기가 괄호로 묶인 경우 제거하고, 중복 공백을 정리한다.
    영문 식별자가 들어간 괄호는 보존된다 (예: "Camellia sinensis").
    """
    # 괄호 안에 한자(\u4e00-\u9fff)·공백·구두점만 있는 경우만 제거
    text = re.sub(r'\s*\([\u4e00-\u9fff\s,，.。·]+\)\s*', '', node_id)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ──────────────────────────────────────────────
# 5. 파싱 헬퍼
# ──────────────────────────────────────────────

def _strip_code_fence(raw: str) -> str:
    """LLM이 ```json ... ``` 으로 감싼 경우 펜스를 제거한다."""
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
    return raw


def _allowed_node_map(allowed_node_ids: set[str] | None) -> dict[str, str] | None:
    """정규화된 노드 ID → 확정 표시 ID 매핑."""
    if allowed_node_ids is None:
        return None
    return {
        _normalize_node_id(node_id): node_id
        for node_id in allowed_node_ids
    }


def _parse_node_candidates(data: dict) -> list[NodeCandidate]:
    """LLM 응답 dict에서 노드 후보만 추출한다."""
    candidates: list[NodeCandidate] = []
    for node in data.get("nodes", []):
        if not isinstance(node, dict) or "id" not in node:
            logger.warning("형식 오류 노드 후보 폐기: %s", node)
            continue

        node_id = str(node["id"]).strip()
        source_quote = str(node.get("source_quote", "")).strip()
        if not node_id or not source_quote:
            logger.warning("필드 누락 노드 후보 폐기: %s", node)
            continue

        candidates.append(NodeCandidate(id=node_id, source_quote=source_quote))

    return candidates


def _parse_to_dataclass(
    data: dict,
    allowed_node_ids: set[str] | None = None,
) -> ExtractionResult:
    """
    LLM 응답 dict를 데이터클래스로 변환한다.

    이 단계에서 다음 검증을 수행하며, 위반 항목은 폐기한다 (방어선 1):
      - 노드: id 필수
      - 체크리스트: item, source_quote 모두 비어있지 않아야 함 (인용 강제)
      - 엣지: source/target 필수, relation은 허용 타입만 채택 (외 → '포함한다')
      - allowed_node_ids가 있으면 그 목록 밖 노드/엣지는 폐기
    """
    allowed_map = _allowed_node_map(allowed_node_ids)

    nodes: list[NodeWithChecklist] = []
    best_node_by_id: dict[str, NodeWithChecklist] = {}
    for node in data.get("nodes", []):
        if not isinstance(node, dict) or "id" not in node:
            logger.warning("형식 오류 노드 폐기: %s", node)
            continue

        raw_node_id = str(node["id"]).strip()
        if not raw_node_id:
            continue
        if allowed_map is not None:
            normalized_id = _normalize_node_id(raw_node_id)
            if normalized_id not in allowed_map:
                logger.warning("확정 목록 밖 노드 폐기: %s", raw_node_id)
                continue
            node_id = allowed_map[normalized_id]
        else:
            node_id = raw_node_id

        checklist: list[ChecklistItem] = []
        for item in node.get("checklist", []):
            if not isinstance(item, dict):
                continue
            if "item" not in item or "source_quote" not in item:
                logger.warning("필드 누락 체크리스트 항목 폐기: %s", item)
                continue
            if not str(item["source_quote"]).strip():
                logger.warning(
                    "빈 source_quote — 인용 강제 위반으로 항목 폐기: %s", item
                )
                continue
            checklist.append(ChecklistItem(
                item=str(item["item"]).strip(),
                source_quote=str(item["source_quote"]).strip(),
            ))

        parsed_node = NodeWithChecklist(id=node_id, checklist=checklist)
        existing = best_node_by_id.get(node_id)
        if existing is None or len(parsed_node.checklist) > len(existing.checklist):
            best_node_by_id[node_id] = parsed_node

    nodes = [
        best_node_by_id[node_id]
        for node_id in sorted(best_node_by_id, key=_normalize_node_id)
    ]

    edges: list[EdgeData] = []
    for edge in data.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if not all(k in edge for k in ("source", "target")):
            continue

        raw_src = str(edge["source"]).strip()
        raw_tgt = str(edge["target"]).strip()
        if allowed_map is not None:
            norm_src = _normalize_node_id(raw_src)
            norm_tgt = _normalize_node_id(raw_tgt)
            if norm_src not in allowed_map or norm_tgt not in allowed_map:
                logger.warning(
                    "확정 목록 밖 엣지 폐기: %s -[%s]-> %s",
                    raw_src, edge.get("relation", ""), raw_tgt,
                )
                continue
            src = allowed_map[norm_src]
            tgt = allowed_map[norm_tgt]
        else:
            src = raw_src
            tgt = raw_tgt

        rel = str(edge.get("relation", "")).strip()
        if rel not in _ALLOWED_RELATIONS:
            logger.warning(
                "비허용 relation '%s' 감지 — '포함한다'로 fallback", rel
            )
            rel = RelationType.CONTAINS.value

        edges.append(EdgeData(
            source=src,
            relation=rel,
            target=tgt,
        ))

    return ExtractionResult(nodes=nodes, edges=edges)


def _choose_display_id(counter: dict[str, int]) -> str:
    """동률이어도 항상 같은 표시 ID를 선택한다."""
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _merge_node_candidate_runs(
    runs: list[list[NodeCandidate]],
    min_appearances: int | None = None,
) -> list[str]:
    """
    노드 후보 run들을 consensus로 병합해 확정 노드 ID 목록을 만든다.

    정규화된 ID 기준으로 과반수 이상 등장한 후보만 채택한다.
    """
    if not runs:
        return []

    threshold = min_appearances or (len(runs) // 2 + 1)
    threshold = max(1, min(threshold, len(runs)))

    appearances: dict[str, int] = defaultdict(int)
    display_id_counter: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for run in runs:
        seen_in_run: set[str] = set()
        for candidate in run:
            norm_id = _normalize_node_id(candidate.id)
            if not norm_id:
                continue
            seen_in_run.add(norm_id)
            display_id_counter[norm_id][candidate.id] += 1
        for norm_id in seen_in_run:
            appearances[norm_id] += 1

    final_node_ids: list[str] = []
    for norm_id in sorted(display_id_counter):
        if appearances[norm_id] < threshold:
            logger.info(
                "노드 후보 '%s' 폐기 — 등장 %d/%d회, 채택 기준 %d회 미달",
                _choose_display_id(display_id_counter[norm_id]),
                appearances[norm_id], len(runs), threshold,
            )
            continue
        final_node_ids.append(_choose_display_id(display_id_counter[norm_id]))

    logger.info(
        "노드 후보 consensus 완료 — 확정 노드 %d개 (채택 기준 %d/%d회)",
        len(final_node_ids), threshold, len(runs),
    )
    return final_node_ids


# ──────────────────────────────────────────────
# 6. 단일 LLM 호출
# ──────────────────────────────────────────────

def _generate_node_candidate_run(
    text: str,
    model: str = KG_DEFAULT_MODEL,
    temperature: float = 0.0,
) -> list[NodeCandidate]:
    """LLM을 1회 호출하여 노드 후보만 추출한다."""
    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": _NODE_CANDIDATE_EXTRACTION_PROMPT + text}
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    raw = _strip_code_fence(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(
            "Reference KG 노드 후보 JSON 파싱 실패: %s\n원본 앞부분: %.500s", e, raw
        )
        raise ValueError(f"LLM이 올바른 JSON을 반환하지 않았습니다: {e}") from e

    return _parse_node_candidates(data)


def _build_fixed_node_detail_prompt(text: str, node_ids: list[str]) -> str:
    """확정 노드 목록을 기존 상세 KG 프롬프트에 주입한다."""
    node_list = "\n".join(f"- {node_id}" for node_id in node_ids)
    instructions = _FIXED_NODE_DETAIL_INSTRUCTIONS.format(node_list=node_list)
    return (
        _REFERENCE_KG_EXTRACTION_PROMPT.replace(
            "학습 자료:\n",
            instructions + "\n학습 자료:\n",
        )
        + text
    )


def _generate_detail_run(
    text: str,
    node_ids: list[str],
    model: str = KG_DEFAULT_MODEL,
    temperature: float = 0.0,
) -> ExtractionResult:
    """확정 노드 목록 안에서 체크리스트와 엣지를 생성한다."""
    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": _build_fixed_node_detail_prompt(text, node_ids)}
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    raw = _strip_code_fence(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(
            "Reference KG 상세 JSON 파싱 실패: %s\n원본 앞부분: %.500s", e, raw
        )
        raise ValueError(f"LLM이 올바른 JSON을 반환하지 않았습니다: {e}") from e

    return _parse_to_dataclass(data, allowed_node_ids=set(node_ids))

def _generate_single_run(
    text: str,
    model: str = KG_DEFAULT_MODEL,
    temperature: float = 0.0,
) -> ExtractionResult:
    """
    LLM을 1회 호출하여 KG + 체크리스트를 추출한다.
    """
    response = _openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": _REFERENCE_KG_EXTRACTION_PROMPT + text}
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    raw = _strip_code_fence(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(
            "Reference KG JSON 파싱 실패: %s\n원본 앞부분: %.500s", e, raw
        )
        raise ValueError(f"LLM이 올바른 JSON을 반환하지 않았습니다: {e}") from e

    return _parse_to_dataclass(data)


# ──────────────────────────────────────────────
# 7. Self-Consistency 병합 (방어선 3) — consensus 정책
# ──────────────────────────────────────────────

def _merge_runs_by_consensus(
    runs: list[ExtractionResult],
    min_appearances: int | None = None,
) -> ExtractionResult:
    """
    여러 호출 결과를 다수결로 병합한다 (일관성 우선 정책).

    정책:
      - 노드: min_appearances회 이상 등장하면 채택 (정규화된 ID 기준 중복 제거)
      - 체크리스트: 같은 노드에 대해 가장 항목 수가 많은 호출의 것을 채택
      - 엣지: min_appearances회 이상 등장하면 채택 (정규화된 (src, rel, tgt) 기준)
      - 체크리스트 0개 노드는 폐기 (평가 불가)

    단일 호출일 때는 min_appearances=1로 동작한다. 다회 호출일 때는 기본적으로
    과반수(floor(n_runs / 2) + 1) 이상 반복 등장한 항목만 채택해, 같은 자료를 다시
    업로드했을 때 KG가 덜 흔들리도록 한다.
    """
    if not runs:
        return ExtractionResult(nodes=[], edges=[])

    threshold = min_appearances or (len(runs) // 2 + 1)
    threshold = max(1, min(threshold, len(runs)))

    # ── 노드 등장 횟수 집계 + 가장 풍부한 체크리스트 선택 ───
    best_nodes: dict[str, NodeWithChecklist] = {}
    node_appearances: dict[str, int] = defaultdict(int)
    display_id_counter: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for run in runs:
        seen_in_run: set[str] = set()
        for node in run.nodes:
            norm_id = _normalize_node_id(node.id)
            seen_in_run.add(norm_id)
            display_id_counter[norm_id][node.id] += 1

            existing = best_nodes.get(norm_id)
            # 체크리스트 항목 수가 더 많은 호출 결과를 채택
            if existing is None or len(node.checklist) > len(existing.checklist):
                best_nodes[norm_id] = node
        for norm_id in seen_in_run:
            node_appearances[norm_id] += 1

    final_nodes: list[NodeWithChecklist] = []
    for norm_id, node in sorted(best_nodes.items(), key=lambda item: item[0]):
        if node_appearances[norm_id] < threshold:
            logger.info(
                "노드 '%s' 폐기 — 등장 %d/%d회, 채택 기준 %d회 미달",
                node.id, node_appearances[norm_id], len(runs), threshold,
            )
            continue
        if not node.checklist:
            logger.warning(
                "노드 '%s' 폐기 — 어느 호출에서도 체크리스트가 없음", node.id
            )
            continue
        # 가장 자주 등장한 원본 표기 채택
        display_id = _choose_display_id(display_id_counter[norm_id])
        final_nodes.append(NodeWithChecklist(
            id=display_id,
            checklist=node.checklist,
        ))

    accepted_norm_ids = {
        _normalize_node_id(n.id)
        for n in final_nodes
        if n.checklist
    }

    # ── 엣지 다수결 ────────────────────────────────────────
    edge_seen: dict[tuple[str, str, str], tuple[str, str]] = {}
    edge_appearances: dict[tuple[str, str, str], int] = defaultdict(int)

    for run in runs:
        seen_in_run: set[tuple[str, str, str]] = set()
        for e in run.edges:
            norm_src = _normalize_node_id(e.source)
            norm_tgt = _normalize_node_id(e.target)
            if (norm_src not in accepted_norm_ids
                    or norm_tgt not in accepted_norm_ids):
                continue
            key = (norm_src, e.relation, norm_tgt)
            seen_in_run.add(key)
            if key not in edge_seen:
                src_display = _choose_display_id(display_id_counter[norm_src])
                tgt_display = _choose_display_id(display_id_counter[norm_tgt])
                edge_seen[key] = (src_display, tgt_display)
        for key in seen_in_run:
            edge_appearances[key] += 1

    final_edges: list[EdgeData] = []
    for key, (src_display, tgt_display) in sorted(edge_seen.items()):
        _, rel, _ = key
        if edge_appearances[key] < threshold:
            logger.info(
                "엣지 '%s -[%s]-> %s' 폐기 — 등장 %d/%d회, 채택 기준 %d회 미달",
                src_display, rel, tgt_display,
                edge_appearances[key], len(runs), threshold,
            )
            continue
        final_edges.append(
            EdgeData(source=src_display, relation=rel, target=tgt_display)
        )

    avg_nodes = sum(len(r.nodes) for r in runs) / len(runs)
    avg_edges = sum(len(r.edges) for r in runs) / len(runs)
    logger.info(
        "Consensus 병합 완료 — 최종 노드 %d개, 엣지 %d개 "
        "(채택 기준 %d/%d회, 호출별 평균: 노드 %.1f, 엣지 %.1f)",
        len(final_nodes), len(final_edges), threshold, len(runs),
        avg_nodes, avg_edges,
    )

    return ExtractionResult(nodes=final_nodes, edges=final_edges)


def _merge_runs_by_union(
    runs: list[ExtractionResult],
) -> ExtractionResult:
    """이전 이름 호환용 래퍼. 실제 병합은 consensus 정책을 사용한다."""
    return _merge_runs_by_consensus(runs)


# ──────────────────────────────────────────────
# 8. 엣지 방향 모순 제거 [PATCH v3-3]
# ──────────────────────────────────────────────

# 의미적 역관계 쌍 — 같은 두 노드 사이에 이 쌍이 양방향으로 존재할 경우
# 한쪽만 남긴다 (둘 다 "포함" 의미라 중복).
_INVERSE_RELATION_PAIRS = [
    ("포함한다",     "구성요소이다"),
    ("종류이다",     "예시이다"),
]

# 엣지 방향 모순이 있을 때 더 신뢰할 수 있는 relation
# 묶음/소속 의미는 "포함한다"(상위→하위 자연 방향)을 우선한다.
_PREFERRED_RELATION_ORDER = [
    "포함한다",
    "구성요소이다",
    "종류이다",
    "예시이다",
    "사용한다",
    "전제한다",
    "가능하게 한다",
    "야기한다",
    "특성을 가진다",
]


def _resolve_edge_direction_conflicts(
    edges: list[EdgeData],
) -> list[EdgeData]:
    """
    같은 두 노드 사이의 양방향 모순 엣지를 정리한다 (이슈 3 해결).

    처리 케이스:
      Case 1 - 의미 동등 역관계 양방향:
        A -[포함한다]-> B  +  B -[구성요소이다]-> A
        → 의미 동일 (둘 다 "A가 B를 포함")이므로 한 방향만 남김.
        → 자연스러운 상위→하위 방향(포함한다)을 우선 채택.

      Case 2 - 의미 모순 양방향:
        A -[포함한다]-> B  +  B -[포함한다]-> A
        → _PREFERRED_RELATION_ORDER에서 더 앞선 relation 우선.

      Case 3 - 의미적으로 부적절한 relation:
        A -[특성을 가진다]-> B 인데 B가 명백히 A의 하위 시대/구성요소인 경우.
        → 이 패턴은 LLM이 "사용한다", "특성을 가진다"를 잘못 붙이는 케이스로,
          같은 두 노드 사이에 더 자연스러운 다른 엣지가 이미 있으면 폐기.

    Returns:
        모순이 해결된 엣지 리스트
    """
    # (norm_src, norm_tgt) → list[EdgeData]
    pair_edges: dict[tuple[str, str], list[EdgeData]] = defaultdict(list)
    for e in edges:
        norm_src = _normalize_node_id(e.source)
        norm_tgt = _normalize_node_id(e.target)
        pair_edges[(norm_src, norm_tgt)].append(e)

    final_edges: list[EdgeData] = []
    processed_pairs: set[tuple[str, str]] = set()

    for (norm_a, norm_b), forward_edges in pair_edges.items():
        unordered_pair = tuple(sorted([norm_a, norm_b]))
        if unordered_pair in processed_pairs:
            continue
        if norm_a == norm_b:
            # 자기 자신 엣지는 그대로 통과 (드문 케이스)
            final_edges.extend(forward_edges)
            processed_pairs.add(unordered_pair)
            continue

        backward_edges = pair_edges.get((norm_b, norm_a), [])

        if not backward_edges:
            # 한 방향만 존재 — 그대로 채택
            final_edges.extend(forward_edges)
            processed_pairs.add(unordered_pair)
            continue

        # ── 양방향 존재 — 모순 해결 ─────────────────────
        forward_rels = {e.relation for e in forward_edges}
        backward_rels = {e.relation for e in backward_edges}

        chosen: EdgeData | None = None

        # Case 1: 의미 동등 역관계 쌍이 양방향에 있는 경우
        for rel_a, rel_b in _INVERSE_RELATION_PAIRS:
            # 자연 방향(rel_a) 채택을 우선
            if rel_a in forward_rels and rel_b in backward_rels:
                chosen = next(e for e in forward_edges if e.relation == rel_a)
                logger.warning(
                    "엣지 방향 모순(의미 동등) 정리: %s -[%s]-> %s 채택, "
                    "역방향 폐기",
                    chosen.source, rel_a, chosen.target,
                )
                break
            if rel_b in forward_rels and rel_a in backward_rels:
                chosen = next(
                    e for e in backward_edges if e.relation == rel_a
                )
                logger.warning(
                    "엣지 방향 모순(의미 동등) 정리: %s -[%s]-> %s 채택, "
                    "역방향 폐기",
                    chosen.source, rel_a, chosen.target,
                )
                break

        # Case 2/3: 의미 동등 쌍이 아닌 경우 — 선호 순서로 한 방향만 채택
        if chosen is None:
            all_candidates = forward_edges + backward_edges
            chosen = min(
                all_candidates,
                key=lambda e: (
                    _PREFERRED_RELATION_ORDER.index(e.relation)
                    if e.relation in _PREFERRED_RELATION_ORDER
                    else 99
                ),
            )
            logger.warning(
                "엣지 방향 모순(혼합) 정리: %s -[%s]-> %s 채택, "
                "총 %d개 엣지에서 1개로 축소",
                chosen.source, chosen.relation, chosen.target,
                len(all_candidates),
            )

        final_edges.append(chosen)
        processed_pairs.add(unordered_pair)

    return final_edges


# ──────────────────────────────────────────────
# 8.5. 묶음 노드 체크리스트 정리 [PATCH v3.1-1, v3.2-1]
# ──────────────────────────────────────────────

# 매칭 대상 최소 길이 — 이보다 짧은 노드 ID는 너무 흔한 단어일 가능성이 높아
# 거짓 양성을 만들기 쉬움. "차", "물" 같은 1~2자 단어는 메타 평가 판별에서 제외.
_MIN_NODE_ID_LEN_FOR_MATCH = 3


def _is_word_match(item_text: str, target_id: str) -> bool:
    """
    item_text 안에 target_id가 "단어 단위"로 등장하는지 검사.

    한국어는 조사가 단어 뒤에 자유롭게 결합되므로(`녹차의`, `TCP가`, `백차에서`),
    뒤 문자는 검사하지 않고 **앞 문자만** 한글이 아닐 것을 요구한다.
    이렇게 하면:
      - "녹차의 특징을 설명"에서 "녹차" → 매칭 (조사 "의" 허용)
      - "한국차 마시기"에서 "차" → 거부 (앞에 한글 "국" 있음, 부분 문자열)

    추가 안전장치: _MIN_NODE_ID_LEN_FOR_MATCH=3 규칙이 짧은 노드 ID
    ("차" 같은 단일 글자)를 매칭 대상에서 제외하여 거짓 양성을 추가 차단한다.
    """
    if target_id not in item_text:
        return False
    start = 0
    while True:
        idx = item_text.find(target_id, start)
        if idx == -1:
            return False
        # 앞 문자만 검사: 한글이면 부분 문자열로 간주하고 거부
        if idx > 0:
            before_char = item_text[idx - 1]
            if '\uac00' <= before_char <= '\ud7a3':
                start = idx + 1
                continue
        return True


def _filter_meta_checklist_items(
    nodes: list[NodeWithChecklist],
) -> list[NodeWithChecklist]:
    """
    묶음 노드의 체크리스트에서 "하위 노드 메타 평가" 항목을 제거한다.
    (이슈 1, 2 후처리 — (2-7) 규칙의 결정론적 강제)

    판별 로직 (v3.2 보강):
      어떤 노드 M의 체크리스트 항목 텍스트에 다른 노드 H의 id가
      **단어 단위로** 포함되어 있고, 그 H가 KG에 별도 노드로 존재하면,
      그 항목은 H에 대한 메타 평가로 간주하여 폐기한다.

    안전장치 4가지:
      (1) 단어 경계 매칭 — 부분 문자열 매칭 거짓 양성 차단
      (2) 짧은 노드 ID(3자 미만) 매칭 대상 제외
      (3) 자기 노드 ID도 항목에 포함되면 정상 항목으로 간주
          (자기 정의를 다른 개념과 비교/대조하는 정상 케이스)
      (4) 모든 항목이 폐기되어 0개가 되는 노드는 폐기 자체를 취소
          (전체가 잘려나가는 건 판별 오류 신호)
    """
    # 정규화된 ID → 원본 ID 매핑 (3자 이상만 매칭 대상)
    node_id_norm_map: dict[str, str] = {
        _normalize_node_id(n.id): n.id
        for n in nodes
        if len(_normalize_node_id(n.id)) >= _MIN_NODE_ID_LEN_FOR_MATCH
    }

    cleaned_nodes: list[NodeWithChecklist] = []
    total_removed = 0
    total_canceled = 0

    for node in nodes:
        node_norm = _normalize_node_id(node.id)
        kept_items: list[ChecklistItem] = []
        removed_items: list[tuple[ChecklistItem, str]] = []

        for ck in node.checklist:
            item_text = ck.item

            # 안전장치 (3): 항목에 자기 노드 ID도 포함되어 있는가?
            self_present = _is_word_match(item_text, node.id) or (
                node_norm != node.id
                and _is_word_match(item_text, node_norm)
            )
            if self_present:
                # 자기 정의 항목 — 정상 항목으로 유지
                kept_items.append(ck)
                continue

            # 다른 노드 ID가 단어 단위로 포함되어 있는지 검사
            referenced_other_node: str | None = None
            for other_norm, other_original in node_id_norm_map.items():
                if other_norm == node_norm:
                    continue
                if (_is_word_match(item_text, other_norm)
                        or _is_word_match(item_text, other_original)):
                    referenced_other_node = other_original
                    break

            if referenced_other_node:
                removed_items.append((ck, referenced_other_node))
                continue

            kept_items.append(ck)

        # 안전장치 (4): 모두 폐기되었으면 원래대로 복구
        if removed_items and not kept_items:
            logger.warning(
                "노드 '%s' — 모든 체크리스트 항목이 메타 평가로 판정되어 "
                "폐기 자체를 취소함 (판별 오류 가능성)",
                node.id,
            )
            cleaned_nodes.append(node)  # 원본 그대로 유지
            total_canceled += 1
            continue

        # 정상 폐기 진행
        for removed_ck, ref_node in removed_items:
            logger.warning(
                "묶음 노드 체크리스트 정리: '%s'에서 '%s'에 대한 "
                "메타 항목 폐기 — \"%s\"",
                node.id, ref_node, removed_ck.item,
            )
            total_removed += 1

        cleaned_nodes.append(NodeWithChecklist(
            id=node.id,
            checklist=kept_items,
        ))

    if total_removed > 0 or total_canceled > 0:
        logger.info(
            "묶음 노드 체크리스트 정리 완료 — 총 %d개 메타 항목 폐기, "
            "%d개 노드는 안전망으로 폐기 취소",
            total_removed, total_canceled,
        )

    return cleaned_nodes


# ──────────────────────────────────────────────
# 8.6. 자기 자신 엣지 폐기 [PATCH v3.1-2]
# ──────────────────────────────────────────────

def _remove_self_loop_edges(edges: list[EdgeData]) -> list[EdgeData]:
    """
    source == target 인 자기 자신 엣지를 폐기한다.

    LLM이 가끔 노드를 자기 자신에게 연결하는 경우가 있는데,
    KG 의미상 자기 참조 엣지는 무의미하다 (특수한 재귀 구조 외).
    """
    cleaned: list[EdgeData] = []
    removed = 0

    for e in edges:
        if _normalize_node_id(e.source) == _normalize_node_id(e.target):
            logger.warning(
                "자기 자신 엣지 폐기: %s -[%s]-> %s",
                e.source, e.relation, e.target,
            )
            removed += 1
            continue
        cleaned.append(e)

    if removed > 0:
        logger.info("자기 자신 엣지 폐기 완료 — %d개 제거", removed)

    return cleaned


# ──────────────────────────────────────────────
# 8.7. 관계 표현 노드 제거 [PATCH v4-1]
# ──────────────────────────────────────────────

_RELATION_NODE_PATTERN = re.compile(
    r'[가-힣\w]+[와과]\s+[가-힣\w\s]+(의\s+)?(관계|차이|비교)',
)


def _remove_relation_nodes(nodes: list[NodeWithChecklist]) -> list[NodeWithChecklist]:
    """
    "A와 B의 관계/차이/비교" 형태 노드를 탐지해 제거한다. ((1-6) 규칙 강제)

    두 개념 사이의 관계는 엣지로 표현해야 하며, 관계 자체를 노드로 만드는 것은
    KG 구조상 잘못된 패턴이다.
    """
    kept = []
    removed = 0
    for node in nodes:
        if _RELATION_NODE_PATTERN.search(node.id):
            logger.warning("관계 표현 노드 제거: '%s'", node.id)
            removed += 1
        else:
            kept.append(node)
    if removed > 0:
        logger.info("관계 표현 노드 제거 완료 — %d개 제거", removed)
    return kept


# ──────────────────────────────────────────────
# 8.8. 별칭 노드 제거 [PATCH v4-2]
# ──────────────────────────────────────────────

_ALIAS_PATTERN = re.compile(
    r'(별칭으로|별칭이다|동의어|라고도\s*불|이라고도\s*불)',
)


def _remove_alias_nodes(nodes: list[NodeWithChecklist]) -> list[NodeWithChecklist]:
    """
    별칭·동의어로 판별된 노드를 제거한다. ((1-6) 규칙 강제)

    판별 기준: 체크리스트 item 또는 source_quote에 별칭 지시 표현이 포함된 경우.
    해당 노드는 다른 개념의 다른 이름일 뿐이므로 독립 노드로 유지할 필요가 없다.
    """
    kept = []
    removed = 0
    for node in nodes:
        is_alias = any(
            _ALIAS_PATTERN.search(ck.item) or _ALIAS_PATTERN.search(ck.source_quote)
            for ck in node.checklist
        )
        if is_alias:
            logger.warning("별칭 노드 제거: '%s'", node.id)
            removed += 1
        else:
            kept.append(node)
    if removed > 0:
        logger.info("별칭 노드 제거 완료 — %d개 제거", removed)
    return kept


# ──────────────────────────────────────────────
# 8.9. 부모 엣지 추론 [PATCH v4-3]
# ──────────────────────────────────────────────

# 부모-자식 관계를 나타내는 한국어 연결 패턴
# "X의 ..." → X의 하위 개념,  "X 처리 ..." / "X 상태 ..." 등
_PARENT_BRIDGE_PATTERNS = ('의', ' 처리', ' 상태', ' 관리', ' 방식')


def _infer_parent_edges(graph: nx.DiGraph) -> nx.DiGraph:
    """
    고립된(in-degree=0) 노드의 이름에서 부모 노드를 추론해 엣지를 추가한다.

    패턴: 노드 이름 = 다른 노드 이름 + bridge + 나머지
      예) "교착 상태의 4가지 조건" → '교착 상태' + '의 4가지 조건'
          "교착 상태 처리 전략"   → '교착 상태' + ' 처리 전략'
          "멀티스레딩의 장단점"   → '멀티스레딩' + '의 장단점'
          "프로세스 상태 전이"    → '프로세스' + ' 상태 전이'
    """
    nodes = list(graph.nodes())
    added = 0

    for node in nodes:
        if graph.in_degree(node) > 0:
            continue
        if not graph.nodes[node].get('checklist'):  # 루트 노드 자신 스킵
            continue

        best_parent: str | None = None
        best_len = 0

        for candidate in nodes:
            if candidate == node or len(candidate) >= len(node):
                continue
            if not node.startswith(candidate):
                continue
            suffix = node[len(candidate):]
            if any(suffix.startswith(bridge) for bridge in _PARENT_BRIDGE_PATTERNS):
                if len(candidate) > best_len:
                    best_parent = candidate
                    best_len = len(candidate)

        if best_parent:
            # 역방향 엣지가 있으면 제거 후 올바른 방향으로 추가 (사이클 방지)
            if graph.has_edge(node, best_parent):
                graph.remove_edge(node, best_parent)
                logger.warning(
                    "역방향 엣지 제거: '%s' → '%s' (부모 추론으로 방향 수정)",
                    node, best_parent,
                )
            graph.add_edge(best_parent, node, relation="포함한다", status="reference")
            logger.info(
                "부모 엣지 추론: '%s' -[포함한다]-> '%s'", best_parent, node
            )
            added += 1

    if added > 0:
        logger.info("부모 엣지 추론 완료 — %d개 추가", added)
    return graph


# ──────────────────────────────────────────────
# 8.10. 단일 부모 강제 [PATCH v4-4]
# ──────────────────────────────────────────────

def _enforce_single_parent(graph: nx.DiGraph) -> nx.DiGraph:
    """
    in-degree > 1인 노드에서 가장 적합한 부모 엣지 하나만 남긴다.

    선택 기준 (우선순위 순):
      1. _PREFERRED_RELATION_ORDER 인덱스가 낮을수록 우선
      2. 동점이면 부모 노드의 out-degree가 높은 쪽 (더 일반적인 상위 개념)
    """
    pruned = 0
    for node in list(graph.nodes()):
        in_edges = list(graph.in_edges(node, data=True))
        if len(in_edges) <= 1:
            continue

        def edge_priority(edge):
            src, _, data = edge
            rel = data.get("relation", "")
            rel_rank = (
                _PREFERRED_RELATION_ORDER.index(rel)
                if rel in _PREFERRED_RELATION_ORDER
                else 99
            )
            return (rel_rank, -graph.out_degree(src))

        sorted_edges = sorted(in_edges, key=edge_priority)
        best_src = sorted_edges[0][0]

        for src, tgt, _ in sorted_edges[1:]:
            graph.remove_edge(src, tgt)
            pruned += 1
            logger.warning(
                "단일 부모 강제: '%s' → '%s' 엣지 제거 (유지 부모: '%s')",
                src, tgt, best_src,
            )

    if pruned > 0:
        logger.info("단일 부모 강제 완료 — %d개 엣지 제거", pruned)
    return graph


# ──────────────────────────────────────────────
# 8.11. 루트 직접 자식 클러스터링 [PATCH v4-5]
# ──────────────────────────────────────────────

_MAX_ROOT_CHILDREN = 6  # 이 수를 초과하면 클러스터링 실행

_ROOT_CLUSTERING_PROMPT = """\
지식 그래프에서 루트 노드 "{root}"의 직접 자식이 {n_children}개로 너무 많아
그래프가 평탄한 구조가 되었습니다. 자식 노드들을 3~6개의 의미 있는 그룹으로
묶어 계층 구조를 만들어주세요.

직접 자식 노드 목록:
{children_list}

규칙:
1. 그룹 수는 3개 이상 6개 이하로 만드세요.
2. 모든 자식 노드는 반드시 정확히 하나의 그룹에 속해야 합니다.
3. [매우 중요] 그룹 이름은 위 목록에 이미 있는 노드 이름을 최우선으로 사용하세요.
   목록의 노드가 다른 노드들의 자연스러운 상위 개념이 된다면 반드시 그 노드를 그룹 이름으로 사용하세요.
   새로운 그룹 이름 생성은 목록 안에 적합한 상위 개념이 없을 때만 허용합니다.
4. 그룹 이름이 목록의 기존 자식 노드인 경우, 그 노드가 그룹 헤더(중간 계층 노드)가 됩니다.
   이 때 members 목록에 자기 자신을 포함하지 마세요.
5. 각 그룹 이름은 해당 자식 노드들을 아우르는 상위 개념이어야 합니다.

반드시 아래 JSON 형식만 반환하세요 (설명, 마크다운 펜스, 주석 없이 순수 JSON):

{{
  "groups": [
    {{
      "name": "중간 노드 이름 (가급적 위 목록에 있는 기존 노드 이름 사용)",
      "members": ["자식노드A", "자식노드B"]
    }}
  ]
}}
"""

_N_CLUSTER_RUNS = 3  # 다수결 호출 횟수


def _run_single_clustering(
    prompt: str,
    model: str,
    children_set: set[str],
    root: str,
    run_idx: int,
    n_total: int,
) -> dict[str, str] | None:
    """
    클러스터링 LLM을 1회 호출하여 자식→그룹 할당 딕셔너리를 반환한다.
    유효성 검증 실패 또는 예외 발생 시 None을 반환한다.
    """
    try:
        response = _openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        raw = _strip_code_fence(raw)
        data = json.loads(raw)
    except Exception as e:
        logger.warning(
            "클러스터링 run %d/%d 실패 — 건너뜀: %s", run_idx, n_total, e
        )
        return None

    groups = data.get("groups", [])
    if not groups:
        logger.warning("클러스터링 run %d/%d 그룹 없음 — 건너뜀", run_idx, n_total)
        return None

    group_names = {str(g.get("name", "")).strip() for g in groups}
    member_names = {str(m) for g in groups for m in g.get("members", [])}
    if root in group_names or (group_names & member_names):
        logger.warning(
            "클러스터링 run %d/%d 유효성 실패 — 건너뜀", run_idx, n_total
        )
        return None

    assignment: dict[str, str] = {}
    for group in groups:
        group_name = str(group.get("name", "")).strip()
        if not group_name:
            continue
        if group_name in children_set:
            assignment[group_name] = group_name  # 헤더 = 자기 자신
        for member in group.get("members", []):
            m = str(member).strip()
            if m in children_set:
                assignment[m] = group_name

    if children_set - set(assignment.keys()):
        logger.warning(
            "클러스터링 run %d/%d 커버리지 부족 — 건너뜀", run_idx, n_total
        )
        return None

    logger.info(
        "클러스터링 run %d/%d 완료 — 그룹 %d개",
        run_idx, n_total, len({v for v in assignment.values()}),
    )
    return assignment


def _cluster_top_nodes(
    graph: nx.DiGraph,
    root_concept: str,
    max_top_nodes: int = _MAX_ROOT_CHILDREN,
    model: str = KG_DEFAULT_MODEL,
    n_cluster_runs: int = _N_CLUSTER_RUNS,
) -> nx.DiGraph:
    """
    in-degree=0인 최상위 노드가 max_top_nodes를 초과하면
    LLM 다수결로 클러스터링하여 중간 계층 노드를 삽입한다. [PATCH v4-5]

    루트 노드 생성 전(_attach_root_node 이전)에 호출한다.
    클러스터링으로 생성된 중간 노드들은 in-degree=0 상태로 남으며,
    이후 _attach_root_node가 이들을 루트에 연결한다.

    처리 흐름:
      1. in-degree=0 최상위 노드 수 확인 → 임계값 이하면 즉시 반환
      2. LLM을 n_cluster_runs회 호출하여 노드→그룹 할당 수집
      3. 노드별 과반수 그룹이 있을 때만 다수결 결과 채택
      4. 다수결 결과로 그룹을 재구성하여 그래프에 적용
         (중간 노드 생성 + 구성원 연결 — 루트 연결은 하지 않음)
      5. 유효 호출 0회 또는 커버리지 부족 시 원본 그래프 유지 (안전망)
    """
    from collections import Counter

    top_nodes = [n for n in graph.nodes() if graph.in_degree(n) == 0]
    if len(top_nodes) <= max_top_nodes:
        return graph

    logger.info(
        "최상위 노드 %d개 → 클러스터링 시작 (임계값: %d, 호출 %d회)",
        len(top_nodes), max_top_nodes, n_cluster_runs,
    )

    top_set = set(top_nodes)
    top_list_str = "\n".join(f"- {n}" for n in sorted(top_nodes))
    prompt = _ROOT_CLUSTERING_PROMPT.format(
        root=root_concept,
        n_children=len(top_nodes),
        children_list=top_list_str,
    )

    # ── n_cluster_runs회 호출하여 노드→그룹 할당 수집 ─────────
    all_assignments: list[dict[str, str]] = []
    for i in range(1, n_cluster_runs + 1):
        assignment = _run_single_clustering(
            prompt, model, top_set, root_concept, i, n_cluster_runs
        )
        if assignment is not None:
            all_assignments.append(assignment)

    if not all_assignments:
        logger.warning("클러스터링 유효 run 없음 — 원본 그래프 유지")
        return graph

    # ── 다수결: 노드별로 가장 많이 선택된 그룹 이름 결정 ──────
    node_to_group: dict[str, str] = {}
    vote_threshold = len(all_assignments) // 2 + 1
    for node in top_nodes:
        votes = Counter(a[node] for a in all_assignments if node in a)
        if votes:
            group_name, vote_count = votes.most_common(1)[0]
            if vote_count < vote_threshold:
                logger.warning(
                    "클러스터링 합의 부족 — '%s' 그룹 투표 %d/%d회, 기준 %d회 미달. 원본 그래프 유지",
                    node, vote_count, len(all_assignments), vote_threshold,
                )
                return graph
            node_to_group[node] = group_name

    uncovered = top_set - set(node_to_group.keys())
    if uncovered:
        logger.warning(
            "다수결 후 미할당 최상위 노드 %s — 원본 그래프 유지", uncovered
        )
        return graph

    logger.info(
        "다수결 완료 (%d회 중 %d회 유효) — 그룹 %d개",
        n_cluster_runs, len(all_assignments),
        len({v for v in node_to_group.values()}),
    )

    # ── 그룹 재구성 ──────────────────────────────────────────
    group_to_members: dict[str, list[str]] = defaultdict(list)
    for node, group_name in node_to_group.items():
        if node != group_name:
            group_to_members[group_name].append(node)
        else:
            group_to_members.setdefault(group_name, [])  # 헤더: 멤버 없음

    # ── 그래프 수정 적용 (루트 연결 제외) ─────────────────────
    for group_name, members in group_to_members.items():
        if group_name not in graph:
            graph.add_node(group_name, status="reference", checklist=[])
            logger.info("새 중간 노드 추가: '%s'", group_name)
        # 기존 최상위 노드가 헤더로 승격된 경우 → 이미 그래프에 존재

        for member in members:
            if member not in graph:
                logger.warning("클러스터링 멤버 '%s' 그래프에 없음 — 스킵", member)
                continue
            if not graph.has_edge(group_name, member) and group_name != member:
                graph.add_edge(
                    group_name, member, relation="포함한다", status="reference"
                )

    after_count = sum(1 for n in graph.nodes() if graph.in_degree(n) == 0)
    logger.info(
        "최상위 노드 클러스터링 완료 — 최상위 노드 %d개 → %d개",
        len(top_nodes), after_count,
    )
    return graph


# ──────────────────────────────────────────────
# 9. 진입점 — Reference KG 생성
# ──────────────────────────────────────────────

def _extract_root_concept(text: str) -> str:
    """텍스트 첫 부분에서 문서 제목/주제를 추출한다."""
    for line in text[:600].split('\n'):
        line = line.strip()
        if 5 <= len(line) <= 60 and not line.startswith('http'):
            return line
    return "학습 자료"


def _attach_root_node(graph: nx.DiGraph, root_concept: str) -> nx.DiGraph:
    """in-degree=0인 최상위 노드들을 루트 노드에 연결한다."""
    if root_concept in graph:
        return graph

    top_level = [n for n in graph.nodes() if graph.in_degree(n) == 0]
    if not top_level:
        return graph

    graph.add_node(root_concept, status="reference", checklist=[])
    for node in top_level:
        graph.add_edge(root_concept, node, relation="포함한다", status="reference")

    logger.info(
        "루트 노드 '%s' 추가 — 최상위 노드 %d개 연결",
        root_concept, len(top_level),
    )
    return graph


def _canonicalize_graph_order(graph: nx.DiGraph) -> nx.DiGraph:
    """노드/엣지 삽입 순서를 고정해 직렬화 결과가 매번 같게 만든다."""
    ordered = nx.DiGraph()

    for node_id, attrs in sorted(
        graph.nodes(data=True),
        key=lambda item: _normalize_node_id(item[0]),
    ):
        attrs_copy = dict(attrs)
        checklist = attrs_copy.get("checklist")
        if isinstance(checklist, list):
            attrs_copy["checklist"] = sorted(
                checklist,
                key=lambda ck: (
                    str(ck.get("item", "")),
                    str(ck.get("source_quote", "")),
                ),
            )
        ordered.add_node(node_id, **attrs_copy)

    for src, tgt, attrs in sorted(
        graph.edges(data=True),
        key=lambda item: (
            _normalize_node_id(item[0]),
            str(item[2].get("relation", "")),
            _normalize_node_id(item[1]),
        ),
    ):
        ordered.add_edge(src, tgt, **attrs)

    return ordered


def generate_reference_kg(
    text_chunks: list[str],
    model: str = KG_DEFAULT_MODEL,
    n_runs: int = 3,
    min_appearances: int | None = None,
    detail_runs: int = 1,
    max_text_chars: int = 12000,
    root_concept: str | None = None,
) -> nx.DiGraph:
    """
    PDF 청크 텍스트로부터 Reference KG를 생성한다.

    파이프라인:
      1. 노드 후보 N회 LLM 호출
      2. 노드 후보 consensus 병합 + 노드 ID 정규화
      3. 확정 노드 목록 안에서 상세 KG 생성
      3. 묶음 노드 체크리스트 정리 (이슈 1, 2 후처리) [v3.1]
      4. 엣지 방향 모순 제거 (이슈 3 후처리)
      5. 자기 자신 엣지 폐기 [v3.1]
      6. NetworkX 그래프 변환
      6.5. 부모 엣지 추론 (소유격/하위개념 패턴) [v4-3]
      6.7. 단일 부모 강제 — in-degree > 1 노드를 트리 구조로 정리 [v4-4]
      7. 최상위 노드 클러스터링 — LLM 3회 다수결로 중간 계층 삽입 [v4-5]
      8. 루트 노드 연결 (부모 없는 노드들을 문서 주제 노드에 연결)

    체크리스트 생성은 PDF 업로드 시 1회만 실행되므로,
    N회 호출에 따른 비용 증가가 사용자 사용 시점 비용에는 영향이 없다.

    Args:
        text_chunks      : extract_and_chunk_pdf()에서 추출된 청크 텍스트 목록
        model            : OpenAI 모델 (기본 KG_DEFAULT_MODEL)
        n_runs           : 노드 후보 LLM 호출 횟수 (기본 3, 최소 1)
        min_appearances  : 노드 후보 채택 최소 등장 횟수
        detail_runs      : 확정 노드 기반 상세 KG 생성 호출 횟수
        max_text_chars   : 합쳐진 텍스트의 최대 길이 (토큰 비용 제한)

    Returns:
        Reference KG (nx.DiGraph). 모든 노드는 status="reference"이며,
        node attributes로 checklist (list[dict])를 가진다:

            graph.nodes["TCP"] == {
                "status": "reference",
                "checklist": [
                    {"item": "...", "source_quote": "..."},
                    ...
                ],
            }

    Raises:
        ValueError      : n_runs 인자가 부적절한 경우
        RuntimeError    : 모든 LLM 호출이 실패한 경우
    """
    if n_runs < 1:
        raise ValueError("n_runs는 1 이상이어야 합니다.")
    if detail_runs < 1:
        raise ValueError("detail_runs는 1 이상이어야 합니다.")

    combined = "\n\n".join(text_chunks)
    if len(combined) > max_text_chars:
        combined = combined[:max_text_chars] + "\n...(이하 생략)"

    logger.info(
        "Reference KG 생성 시작 — 텍스트 %d자, 노드 후보 호출 %d회, 상세 호출 %d회",
        len(combined), n_runs, detail_runs,
    )

    # ── 1. 노드 후보 N회 LLM 호출 ─────────────────────────
    candidate_runs: list[list[NodeCandidate]] = []
    for i in range(n_runs):
        try:
            result = _generate_node_candidate_run(combined, model=model)
            logger.info(
                "  [Node Run %d/%d] 후보 노드 %d개 추출",
                i + 1, n_runs, len(result),
            )
            candidate_runs.append(result)
        except Exception as e:
            logger.warning(
                "  [Node Run %d/%d] 실패 — 건너뜀: %s", i + 1, n_runs, e
            )

    if not candidate_runs:
        raise RuntimeError(
            "모든 노드 후보 LLM 호출이 실패하여 Reference KG를 생성할 수 없습니다."
        )

    # ── 2. 노드 후보 consensus 병합 ───────────────────────
    fixed_node_ids = _merge_node_candidate_runs(
        candidate_runs,
        min_appearances=min_appearances,
    )
    if not fixed_node_ids:
        raise RuntimeError(
            "Consensus 기준을 통과한 노드 후보가 없어 Reference KG를 생성할 수 없습니다."
        )

    # ── 3. 확정 노드 목록 안에서 상세 KG 생성 ─────────────
    detail_results: list[ExtractionResult] = []
    for i in range(detail_runs):
        try:
            result = _generate_detail_run(combined, fixed_node_ids, model=model)
            logger.info(
                "  [Detail Run %d/%d] 노드 %d개, 엣지 %d개 추출",
                i + 1, detail_runs, len(result.nodes), len(result.edges),
            )
            detail_results.append(result)
        except Exception as e:
            logger.warning(
                "  [Detail Run %d/%d] 실패 — 건너뜀: %s", i + 1, detail_runs, e
            )

    if not detail_results:
        raise RuntimeError(
            "모든 상세 KG LLM 호출이 실패하여 Reference KG를 생성할 수 없습니다."
        )

    detail_min_appearances = 1 if detail_runs == 1 else min_appearances
    merged = _merge_runs_by_consensus(
        detail_results,
        min_appearances=detail_min_appearances,
    )

    # ── 3.5. 관계 표현 노드 / 별칭 노드 제거 [PATCH v4] ─────
    filtered_nodes = _remove_relation_nodes(merged.nodes)
    filtered_nodes = _remove_alias_nodes(filtered_nodes)

    # ── 3. 묶음 노드 체크리스트 정리 (이슈 1, 2 후처리) [PATCH v3.1-1] ──
    cleaned_nodes = _filter_meta_checklist_items(filtered_nodes)

    # ── 4. 엣지 방향 모순 제거 (이슈 3 후처리) ────────────
    edges_before = len(merged.edges)
    direction_resolved_edges = _resolve_edge_direction_conflicts(merged.edges)
    if len(direction_resolved_edges) < edges_before:
        logger.info(
            "엣지 방향 모순 제거: %d개 → %d개 (%d개 폐기)",
            edges_before, len(direction_resolved_edges),
            edges_before - len(direction_resolved_edges),
        )

    # ── 5. 자기 자신 엣지 폐기 [PATCH v3.1-2] ─────────────
    cleaned_edges = _remove_self_loop_edges(direction_resolved_edges)

    # ── 6. NetworkX 그래프 변환 ───────────────────────────
    graph = nx.DiGraph()

    for node in cleaned_nodes:
        graph.add_node(
            node.id,
            status="reference",
            checklist=[
                {"item": ck.item, "source_quote": ck.source_quote}
                for ck in node.checklist
            ],
        )

    for edge in cleaned_edges:
        if edge.source not in graph or edge.target not in graph:
            logger.warning(
                "엣지 '%s -[%s]-> %s' 폐기 — 양 끝 노드 누락",
                edge.source, edge.relation, edge.target,
            )
            continue
        graph.add_edge(
            edge.source,
            edge.target,
            relation=edge.relation,
            status="reference",
        )

    # ── 6.5. 부모 엣지 추론 (소유격/하위개념 패턴) [PATCH v4-3] ──
    graph = _infer_parent_edges(graph)

    # ── 6.7. 단일 부모 강제 [PATCH v4-4] ──────────────────
    graph = _enforce_single_parent(graph)

    # ── 7. 최상위 노드 클러스터링 [PATCH v4-5] ──────────────
    root = root_concept or _extract_root_concept(combined)
    graph = _cluster_top_nodes(graph, root, model=model)

    # ── 8. 루트 노드 연결 (부모 없는 노드를 루트에 연결) ──────
    graph = _attach_root_node(graph, root)

    # ── 9. 최종 순서 고정 ─────────────────────────────────
    graph = _canonicalize_graph_order(graph)

    # ── 최종 통계 ──────────────────────────────────────────
    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    avg_checklist = (
        sum(len(graph.nodes[n].get("checklist", [])) for n in graph.nodes())
        / max(n_nodes, 1)
    )
    logger.info(
        "Reference KG 생성 완료 — 노드 %d개, 엣지 %d개, "
        "노드당 평균 체크리스트 항목 %.1f개",
        n_nodes, n_edges, avg_checklist,
    )

    return graph
