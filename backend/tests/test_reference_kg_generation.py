"""
scripts/test_reference_kg_generation.py
---------------------------------------
Reference KG 생성 프롬프트 검증 스크립트.

backend/scripts/ 아래에 배치하고, backend/ 디렉토리에서 실행한다.
실제 OpenAI API를 호출하므로 환경변수 OPENAI_API_KEY가 필요하다.

사용법:
  # 1) 내장 샘플 텍스트로 빠르게 검증
  python -m scripts.test_reference_kg_generation --sample tcp

  # 2) 실제 PDF로 검증
  python -m scripts.test_reference_kg_generation --pdf path/to/lecture.pdf

  # 3) Self-Consistency 끄고 단일 호출 raw 응답 확인 (디버깅용)
  python -m scripts.test_reference_kg_generation --sample tcp --single-run

  # 4) 호출 횟수 / 임계값 조정
  python -m scripts.test_reference_kg_generation --sample tcp --runs 5 --min-appearances 3

  # 5) 결과 JSON 저장
  python -m scripts.test_reference_kg_generation --sample tcp --save out.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from app.services.kg_service import RelationType, serialize_kg
from app.services.reference_kg_generator import (
    _generate_single_run,
    generate_reference_kg,
)

# 진행 로그 보이게
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)

# ──────────────────────────────────────────────
# 1. 내장 샘플 텍스트 — PDF 없이 빠르게 검증할 때 사용
# ──────────────────────────────────────────────

SAMPLES: dict[str, str] = {
    "tcp": """\
[TCP/IP 프로토콜]
TCP는 연결 지향(connection-oriented) 프로토콜이다.
TCP는 손실된 패킷의 재전송과 순서 보장을 통해 신뢰성을 제공한다.
TCP는 SYN, SYN-ACK, ACK의 3단계 과정을 통해 연결을 수립한다.
이 과정을 3-way handshake라고 부른다.

[흐름 제어]
흐름 제어는 송신측이 수신측의 처리 능력을 초과해 데이터를 보내지 않도록 하는 메커니즘이다.
수신 측의 버퍼 크기와 처리 속도를 고려해 송신 속도를 조절한다.
흐름 제어의 대표적 메커니즘은 슬라이딩 윈도우 방식이다.
슬라이딩 윈도우는 수신측이 알려준 윈도우 크기만큼만 데이터를 전송한다.

[혼잡 제어]
혼잡 제어는 네트워크 자체가 혼잡할 때 송신 속도를 줄이는 메커니즘이다.
흐름 제어가 수신측 단말 보호 목적이라면, 혼잡 제어는 네트워크 보호 목적이다.
혼잡 제어는 ACK 신호의 수신 패턴을 통해 네트워크 상태를 파악한다.
혼잡 제어 알고리즘으로는 Slow Start와 Congestion Avoidance가 있다.
""",

    "photosynthesis": """\
[광합성]
광합성은 식물이 빛 에너지를 이용해 이산화탄소와 물에서 포도당과 산소를 생성하는 과정이다.
광합성은 엽록체에서 일어난다.
엽록체에는 엽록소(클로로필)가 들어 있어 빛을 흡수한다.

[광반응]
광반응은 빛 에너지를 화학 에너지(ATP, NADPH)로 변환하는 단계이다.
광반응은 엽록체의 틸라코이드 막에서 일어난다.
광반응은 물을 분해하여 산소를 발생시킨다.

[캘빈 회로]
캘빈 회로는 ATP와 NADPH를 사용해 이산화탄소를 포도당으로 고정하는 단계이다.
캘빈 회로는 엽록체의 스트로마에서 일어난다.
캘빈 회로는 빛이 직접 필요하지 않아 암반응이라고도 불린다.
""",
}


# ──────────────────────────────────────────────
# 2. 출력 포맷터
# ──────────────────────────────────────────────

def print_section(title: str) -> None:
    """섹션 헤더 출력."""
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def print_kg_summary(graph) -> None:
    """KG의 노드/엣지/체크리스트를 사람이 읽기 좋게 출력."""
    print_section(
        f"📊 Reference KG 결과 — "
        f"노드 {graph.number_of_nodes()}개, "
        f"엣지 {graph.number_of_edges()}개"
    )

    # ── 노드 + 체크리스트 ──
    print("\n## 노드 및 체크리스트\n")
    for node_id in sorted(graph.nodes()):
        attrs = graph.nodes[node_id]
        checklist = attrs.get("checklist", [])
        print(f"▶ {node_id}  ({len(checklist)}개 항목)")
        for i, ck in enumerate(checklist, 1):
            print(f"  {i}. {ck['item']}")
            print(f"     ↳ 출처: \"{ck['source_quote']}\"")
        print()

    # ── 엣지 ──
    print("## 엣지 (관계)\n")
    if graph.number_of_edges() == 0:
        print("  (엣지 없음)")
    for src, tgt, attrs in graph.edges(data=True):
        rel = attrs.get("relation", "?")
        print(f"  {src}  -[{rel}]->  {tgt}")


# ──────────────────────────────────────────────
# 3. 자동 검증 — 기획서 §4-1 규칙 준수 여부 체크
# ──────────────────────────────────────────────

def validate_kg(graph, source_text: str) -> bool:
    """
    KG가 기획서 §4-1의 규칙을 준수하는지 자동 검증한다.

    Returns:
        True if 모든 hard 이슈 통과 (warnings는 통과로 간주)
    """
    print_section("🔍 자동 검증")

    issues: list[str] = []  # 반드시 고쳐야 함
    warnings: list[str] = []  # 검토 권장

    # ── 노드 수 검증 ──────────────────────────────────────
    n_nodes = graph.number_of_nodes()
    if n_nodes == 0:
        issues.append("노드가 0개 — 추출 실패")
    elif n_nodes < 5:
        warnings.append(f"노드 수 {n_nodes}개 (목표 5~20, 자료가 짧으면 정상)")
    elif n_nodes > 20:
        warnings.append(f"노드 수 {n_nodes}개 (목표 5~20 초과 — 세분화 과다 가능)")

    # ── 체크리스트 검증 ──────────────────────────────────
    nodes_no_checklist = []
    nodes_too_few = []  # 2개 미만
    nodes_too_many = []  # 4개 초과
    items_no_quote = []
    items_quote_not_in_source = []

    for node_id in graph.nodes():
        cks = graph.nodes[node_id].get("checklist", [])
        if not cks:
            nodes_no_checklist.append(node_id)
            continue
        if len(cks) < 2:
            nodes_too_few.append((node_id, len(cks)))
        if len(cks) > 4:
            nodes_too_many.append((node_id, len(cks)))

        for ck in cks:
            quote = ck.get("source_quote", "").strip()
            if not quote:
                items_no_quote.append(node_id)
                continue
            # 인용이 자료에 실제 등장하는지 검증.
            # 정확히 일치 안 해도 OK (LLM이 마침표/공백 약간 다듬을 수 있음).
            # 첫 15자가 자료에 있는지 부분 매칭으로 확인.
            snippet = quote[:15].strip()
            if snippet and snippet not in source_text:
                items_quote_not_in_source.append((node_id, quote[:60]))

    if nodes_no_checklist:
        issues.append(f"체크리스트 없는 노드: {nodes_no_checklist}")
    if items_no_quote:
        issues.append(f"빈 source_quote 항목 보유 노드: {items_no_quote}")
    if nodes_too_few:
        warnings.append(f"체크리스트 2개 미만 노드: {nodes_too_few}")
    if nodes_too_many:
        warnings.append(f"체크리스트 4개 초과 노드: {nodes_too_many}")
    if items_quote_not_in_source:
        warnings.append(
            f"자료에 부분 매칭 안 되는 인용 (앞 3건): "
            f"{items_quote_not_in_source[:3]}"
        )

    # ── 엣지 검증 ────────────────────────────────────────
    allowed = {r.value for r in RelationType}
    invalid_relations = []
    invalid_endpoints = []
    for src, tgt, attrs in graph.edges(data=True):
        rel = attrs.get("relation")
        if rel not in allowed:
            invalid_relations.append((src, rel, tgt))
        if src not in graph or tgt not in graph:
            invalid_endpoints.append((src, tgt))

    if invalid_relations:
        issues.append(f"비허용 relation: {invalid_relations}")
    if invalid_endpoints:
        issues.append(f"엣지 노드 누락: {invalid_endpoints}")

    # ── 요약 출력 ────────────────────────────────────────
    print(f"\n노드 수:           {n_nodes:>3} "
          f"{'✅' if 5 <= n_nodes <= 20 else '⚠️ '}")
    print(f"엣지 수:           {graph.number_of_edges():>3}")

    avg_ck = (
            sum(len(graph.nodes[n].get('checklist', [])) for n in graph.nodes())
            / max(n_nodes, 1)
    )
    print(f"노드당 평균 체크리스트: {avg_ck:>4.1f}개 "
          f"{'✅' if 2 <= avg_ck <= 4 else '⚠️ '}")

    if not issues and not warnings:
        print("\n✅ 모든 규칙 통과!")
    else:
        if warnings:
            print("\n⚠️  경고 (검토 권장):")
            for w in warnings:
                print(f"  - {w}")
        if issues:
            print("\n❌ 이슈 (수정 필요):")
            for it in issues:
                print(f"  - {it}")

    return not issues


# ──────────────────────────────────────────────
# 4. 단일 호출 모드 — Self-Consistency 우회 디버깅
# ──────────────────────────────────────────────

def run_single_call(source_text: str) -> None:
    """LLM 단일 호출 결과를 그대로 보여준다 (병합 X)."""
    print_section("🔬 단일 호출 모드 (Self-Consistency 미적용)")

    result = _generate_single_run(source_text[:6000], model="gpt-4o-mini")
    print(f"\n노드 {len(result.nodes)}개, 엣지 {len(result.edges)}개\n")

    for node in result.nodes:
        print(f"▶ {node.id}  ({len(node.checklist)}개 항목)")
        for ck in node.checklist:
            quote_preview = (
                ck.source_quote[:50] + "..."
                if len(ck.source_quote) > 50
                else ck.source_quote
            )
            print(f"  - {ck.item}")
            print(f"      ↳ \"{quote_preview}\"")
        print()

    print("\n## 엣지\n")
    for e in result.edges:
        print(f"  {e.source}  -[{e.relation}]->  {e.target}")


# ──────────────────────────────────────────────
# 5. 메인
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reference KG 생성 프롬프트 검증",
    )
    parser.add_argument(
        "--sample",
        choices=list(SAMPLES.keys()),
        help=f"내장 샘플 사용: {list(SAMPLES.keys())}",
    )
    parser.add_argument(
        "--pdf",
        type=str,
        help="PDF 파일 경로",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="LLM 호출 횟수 (기본 3)",
    )
    parser.add_argument(
        "--min-appearances",
        type=int,
        default=2,
        help="Self-Consistency 채택 임계값 (기본 2)",
    )
    parser.add_argument(
        "--single-run",
        action="store_true",
        help="Self-Consistency 우회 — 단일 호출 raw 결과만 출력",
    )
    parser.add_argument(
        "--save",
        type=str,
        help="결과 KG를 JSON으로 저장할 경로",
    )
    args = parser.parse_args()

    # ── 입력 텍스트 준비 ─────────────────────────────────
    if args.sample:
        text_chunks = [SAMPLES[args.sample]]
        source_text = SAMPLES[args.sample]
        print(f"📖 내장 샘플 사용: '{args.sample}'")
    elif args.pdf:
        # 기존 pdf_service 재사용
        from app.services.pdf_service import extract_and_chunk_pdf
        chunk_data = extract_and_chunk_pdf(args.pdf)
        text_chunks = [c["content"] for c in chunk_data]
        source_text = "\n\n".join(text_chunks)
        print(f"📄 PDF 파일 사용: {args.pdf} (청크 {len(chunk_data)}개)")
    else:
        print("❌ --sample 또는 --pdf 중 하나는 반드시 지정해야 합니다.")
        parser.print_help()
        sys.exit(1)

    print(f"   텍스트 길이: {len(source_text):,}자")
    print(f"   호출 횟수:   {args.runs}")
    print(f"   채택 임계값: {args.min_appearances}/{args.runs}")

    # ── 단일 호출 모드 (디버깅용) ────────────────────────
    if args.single_run:
        run_single_call(source_text)
        return

    # ── 정식 생성 ────────────────────────────────────────
    graph = generate_reference_kg(
        text_chunks,
        n_runs=args.runs,
    )

    # ── 결과 출력 + 자동 검증 ────────────────────────────
    print_kg_summary(graph)
    passed = validate_kg(graph, source_text)

    # ── JSON 저장 (옵션) ─────────────────────────────────
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(serialize_kg(graph), f, ensure_ascii=False, indent=2)
        print(f"\n💾 결과 저장: {args.save}")

    print()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
