"""
api/v1/debug_kg.py
---------------
디버깅 전용 엔드포인트 — Reference KG / User KG 시각적 출력.

⚠️  프로덕션 배포 전 반드시 라우터 등록을 제거하거나
    DEBUG_MODE 환경변수로 보호할 것.

등록 방법 (main.py):
    import os
    if os.getenv("DEBUG_MODE", "false").lower() == "true":
        from app.api.v1.debug_kg import router as debug_router
        app.include_router(debug_router)

엔드포인트:
    GET /debug/kg/{document_id}          → JSON 형태 전체 덤프
    GET /debug/kg/{document_id}/pretty   → 터미널 친화적 텍스트 출력
"""

import os
import logging
from typing import Any

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.kg_service import (
    NodeStatus,
    EdgeStatus,
    load_kg_from_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])

# ── 상태별 이모지 매핑 ─────────────────────────────────────
_NODE_EMOJI: dict[str, str] = {
    NodeStatus.CONFIRMED:    "✅",
    NodeStatus.PARTIAL:      "🟡",
    NodeStatus.MISSING:      "❌",
    NodeStatus.MISCONCEPTION: "⚠️ ",
    "reference":             "📌",  # Reference KG 전용
}
_EDGE_EMOJI: dict[str, str] = {
    EdgeStatus.CONFIRMED:    "✅",
    EdgeStatus.PARTIAL:      "🟡",
    EdgeStatus.MISSING:      "❌",
    EdgeStatus.MISCONCEPTION: "⚠️ ",
    "reference":             "📌",
}


# ──────────────────────────────────────────────────────────
# 내부 변환 함수
# ──────────────────────────────────────────────────────────

def _kg_to_dict(graph: nx.DiGraph, kg_type: str = "unknown") -> dict[str, Any]:
    """
    NetworkX DiGraph → JSON 직렬화 가능한 dict 변환.

    kg_type: "reference" | "user"
    """
    nodes = []
    for node_id, attrs in graph.nodes(data=True):
        if node_id == "__misconceptions__":
            # 오개념 특수 노드는 별도 섹션에서 처리
            continue
        node_data: dict[str, Any] = {
            "id":     node_id,
            "status": attrs.get("status", "unknown"),
        }
        if kg_type == "reference":
            # Reference KG: checklist 항목(item + source_quote) 포함
            node_data["checklist"] = attrs.get("checklist", [])
        else:
            # User KG: 평가 결과 및 달성률 포함
            node_data["checklist_result"]  = attrs.get("checklist_result", [])
            node_data["completion_ratio"]  = attrs.get("completion_ratio", 0.0)
        nodes.append(node_data)

    edges = []
    for src, tgt, attrs in graph.edges(data=True):
        edges.append({
            "source":   src,
            "relation": attrs.get("relation", ""),
            "target":   tgt,
            "status":   attrs.get("status", "unknown"),
        })

    # __misconceptions__ 특수 노드 별도 추출 (User KG 전용)
    misconceptions: list[dict] = []
    if "__misconceptions__" in graph:
        misconceptions = graph.nodes["__misconceptions__"].get("items", [])

    result: dict[str, Any] = {
        "kg_type":        kg_type,
        "node_count":     len(nodes),
        "edge_count":     len(edges),
        "nodes":          nodes,
        "edges":          edges,
    }
    if kg_type == "user":
        result["misconceptions"] = misconceptions
        # 커버리지 통계
        status_counts = {s.value: 0 for s in NodeStatus}
        for n in nodes:
            s = n.get("status", "")
            if s in status_counts:
                status_counts[s] += 1
        result["coverage"] = {
            "total":         len(nodes),
            **status_counts,
            "confirmed_ratio": (
                round(status_counts.get("confirmed", 0) / max(len(nodes), 1), 3)
            ),
        }
    return result


def _format_kg_pretty(graph: nx.DiGraph, kg_type: str, document_id: int) -> str:
    """
    터미널 출력용 텍스트 포맷 생성.
    """
    lines: list[str] = []
    sep_thick = "═" * 60
    sep_thin  = "─" * 60

    title = "Reference KG" if kg_type == "reference" else "User KG"
    lines.append(sep_thick)
    lines.append(f"  {title}  |  document_id={document_id}")
    lines.append(sep_thick)

    # ── 노드 섹션 ──────────────────────────────────────────
    real_nodes = [
        (nid, attrs)
        for nid, attrs in graph.nodes(data=True)
        if nid != "__misconceptions__"
    ]
    lines.append(f"\n📦 NODES  ({len(real_nodes)}개)\n" + sep_thin)

    for node_id, attrs in sorted(real_nodes, key=lambda x: x[0]):
        status = attrs.get("status", "unknown")
        emoji  = _NODE_EMOJI.get(status, "❓")
        lines.append(f"  {emoji} [{node_id}]  status={status}")

        if kg_type == "reference":
            checklist = attrs.get("checklist", [])
            if checklist:
                lines.append(f"     체크리스트 ({len(checklist)}항목):")
                for ck in checklist:
                    lines.append(f"       • {ck.get('item', '')}")
                    sq = ck.get("source_quote", "")
                    if sq:
                        # 너무 길면 줄임
                        sq_display = sq[:80] + "…" if len(sq) > 80 else sq
                        lines.append(f"         출처: \"{sq_display}\"")
        else:
            ratio  = attrs.get("completion_ratio", 0.0)
            cr     = attrs.get("checklist_result", [])
            met    = sum(1 for c in cr if c.get("met"))
            total  = len(cr)
            bar    = _progress_bar(ratio)
            lines.append(f"     달성률: {bar} {ratio:.0%}  ({met}/{total} 항목)")
            if cr:
                for c in cr:
                    tick = "✓" if c.get("met") else "✗"
                    lines.append(f"       [{tick}] {c.get('item', '')}")

    # ── 엣지 섹션 ──────────────────────────────────────────
    lines.append(f"\n🔗 EDGES  ({graph.number_of_edges()}개)\n" + sep_thin)

    for src, tgt, attrs in sorted(
        graph.edges(data=True), key=lambda x: (x[0], x[2].get("status", ""))
    ):
        status   = attrs.get("status", "unknown")
        relation = attrs.get("relation", "")
        emoji    = _EDGE_EMOJI.get(status, "❓")
        lines.append(f"  {emoji} {src}  ──[{relation}]──▶  {tgt}  (status={status})")

    # ── User KG 전용: 커버리지 + 오개념 ──────────────────
    if kg_type == "user":
        real_node_count = len(real_nodes)
        status_counts = {s.value: 0 for s in NodeStatus}
        for _, attrs in real_nodes:
            s = attrs.get("status", "")
            if s in status_counts:
                status_counts[s] += 1

        lines.append(f"\n📊 커버리지 통계\n" + sep_thin)
        for s, cnt in status_counts.items():
            emoji = _NODE_EMOJI.get(s, "❓")
            pct   = cnt / max(real_node_count, 1)
            bar   = _progress_bar(pct, width=15)
            lines.append(f"  {emoji} {s:<14} {bar}  {cnt:>2}개  ({pct:.0%})")

        misc_node = graph.nodes.get("__misconceptions__")
        misc_items = misc_node.get("items", []) if misc_node else []
        lines.append(f"\n⚠️  오개념 기록  ({len(misc_items)}건)\n" + sep_thin)
        if misc_items:
            for i, m in enumerate(misc_items, 1):
                lines.append(f"  {i}. {m.get('content', '')}")
                lines.append(f"     → 정정: {m.get('correction', '')}")
        else:
            lines.append("  (없음)")

    lines.append("\n" + sep_thick + "\n")
    return "\n".join(lines)


def _progress_bar(ratio: float, width: int = 10) -> str:
    """간단한 ASCII 진행 막대."""
    filled = round(ratio * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


# ──────────────────────────────────────────────────────────
# FastAPI 엔드포인트
# ──────────────────────────────────────────────────────────

@router.get(
    "/kg/{document_id}",
    summary="KG JSON 덤프",
    description="Reference KG와 User KG 전체 내용을 JSON으로 반환합니다.",
)
def get_kg_debug_json(
    document_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """
    디버그용 KG JSON 덤프.

    Returns:
        {
          "document_id": int,
          "reference_kg": { ... },
          "user_kg": { ... }
        }
    """
    result = load_kg_from_db(db, document_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"document_id={document_id}에 해당하는 KG가 없습니다.",
        )
    reference_kg, user_kg = result

    return {
        "document_id": document_id,
        "reference_kg": _kg_to_dict(reference_kg, kg_type="reference"),
        "user_kg":      _kg_to_dict(user_kg,      kg_type="user"),
    }


@router.get(
    "/kg/{document_id}/pretty",
    summary="KG 텍스트 출력",
    description="Reference KG와 User KG를 터미널 친화적 텍스트로 반환합니다.",
    response_class=PlainTextResponse,
)
def get_kg_debug_pretty(
    document_id: int,
    db: Session = Depends(get_db),
) -> str:
    """
    디버그용 KG Pretty-print.
    브라우저나 curl에서 바로 읽기 좋은 텍스트 형태로 반환.
    """
    result = load_kg_from_db(db, document_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"document_id={document_id}에 해당하는 KG가 없습니다.",
        )
    reference_kg, user_kg = result

    output = ""
    output += _format_kg_pretty(reference_kg, kg_type="reference", document_id=document_id)
    output += _format_kg_pretty(user_kg,      kg_type="user",      document_id=document_id)
    return output


# ──────────────────────────────────────────────────────────
# 스크립트 / pytest 직접 호출용 유틸리티
# ──────────────────────────────────────────────────────────

def print_kg(graph: nx.DiGraph, kg_type: str = "unknown", document_id: int = 0) -> None:
    """
    DB 없이 NetworkX 그래프를 직접 받아 터미널에 출력.

    사용 예시 (pytest / 스크립트):
        from app.api.v1.debug_kg import print_kg
        from app.services.reference_kg_generator import generate_reference_kg

        ref_kg = generate_reference_kg(chunks, document_id=1)
        print_kg(ref_kg, kg_type="reference", document_id=1)
    """
    print(_format_kg_pretty(graph, kg_type=kg_type, document_id=document_id))


def print_both_kg(
    reference_kg: nx.DiGraph,
    user_kg: nx.DiGraph,
    document_id: int = 0,
) -> None:
    """
    Reference KG + User KG 두 개를 연속으로 출력.

    사용 예시:
        from app.api.debug_kg import print_both_kg
        print_both_kg(ref_kg, user_kg, document_id=1)
    """
    print_kg(reference_kg, kg_type="reference", document_id=document_id)
    print_kg(user_kg,      kg_type="user",      document_id=document_id)