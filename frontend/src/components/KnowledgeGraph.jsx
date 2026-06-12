import { useEffect, useRef, useState } from 'react';
import './KnowledgeGraph.css';

function splitLabel(label) {
  const text = String(label || '');
  if (!text) return [''];

  if (text.includes(' ')) {
    const words = text.split(/\s+/).filter(Boolean);
    const lines = [];
    let current = '';
    for (const word of words) {
      if (lines.length >= 3) break;
      if (!current) {
        current = word;
      } else if ((current + ' ' + word).length <= 6) {
        current += ' ' + word;
      } else {
        lines.push(current);
        current = word;
      }
    }
    if (current && lines.length < 3) lines.push(current);
    return lines;
  }

  const lines = [];
  for (let i = 0; i < text.length && lines.length < 3; i += 6) {
    lines.push(text.slice(i, i + 6));
  }
  return lines;
}

function estimateHighlightWidth(line) {
  return Math.min(174, Math.max(42, [...line].length * 14 + 20));
}

function NodeLabel({ label, r, fill, fontWeight, highlight }) {
  const lines = splitLabel(label);
  return (
    <g>
      {highlight && lines.map((line, i) => {
        const y = r + 33 + i * 24;
        const w = estimateHighlightWidth(line);
        return (
          <rect
            key={`hl-${i}`}
            x={-w / 2}
            y={y - 18}
            width={w}
            height={24}
            rx={5}
            fill="#fde68a"
            opacity={0.72}
          />
        );
      })}
      <text textAnchor="middle" fill={fill} fontSize={22}
        fontFamily="Inter,sans-serif" fontWeight={fontWeight}>
        {lines.map((line, i) => (
          <tspan key={i} x={0} y={r + 33 + i * 24}>{line}</tspan>
        ))}
      </text>
    </g>
  );
}

const STATUS_COLOR = {
  confirmed: '#10b981',
  partial: '#f59e0b',
  missing: '#cbd5e1',
  reference: '#cbd5e1',
  active: '#4f6ef7',
  misconception: '#ef4444',
};
const STATUS_STROKE = {
  confirmed: '#059669',
  partial: '#d97706',
  missing: '#94a3b8',
  reference: '#94a3b8',
  active: '#3451d1',
  misconception: '#dc2626',
};
// 레이블이 노드 중심에서 벗어나는 여백
const LBL_X   = 104; // 좌우 (형광펜 라벨 폭 포함)
const LBL_TOP = 34;  // 위
const LBL_BOT = 100;  // 아래 (최대 3줄 레이블 + 여유)

const MIN_ZOOM = 0.7;
const MAX_ZOOM = 2.2;
const ZOOM_STEP = 0.2;
const FIT_MAX_HEIGHT = 160;

function clampZoom(value) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value.toFixed(2))));
}

function isHighImportance(importance) {
  const normalized = String(importance || '').trim().toLowerCase();
  return normalized === 'high';
}

export default function KnowledgeGraph({ nodes, edges, width = 500, height = 340, onNodeClick, selectedNodeId }) {
  const [hovered, setHovered] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [canvasWidth, setCanvasWidth] = useState(0);
  const canvasRef = useRef(null);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setZoom(1));
    return () => cancelAnimationFrame(frame);
  }, [nodes, edges]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const updateWidth = () => {
      setCanvasWidth(Math.max(0, Math.floor(canvas.clientWidth)));
    };
    updateWidth();

    const observer = new ResizeObserver(updateWidth);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  if (!nodes || !edges) return null;

  // 노드 bounding box → viewBox 계산
  // vbW/vbH 최솟값을 width/height로 두어 스케일이 1 이하로만 동작
  let vbX = 0, vbY = 0, vbW = width, vbH = height;
  if (nodes.length > 0) {
    const xs = nodes.map(n => n.x);
    const ys = nodes.map(n => n.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    vbX = minX - LBL_X;
    vbY = minY - LBL_TOP;
    vbW = Math.max(maxX - minX + LBL_X * 2, width);
    vbH = Math.max(maxY - minY + LBL_TOP + LBL_BOT, height);
  }

  const fitScale = canvasWidth
    ? Math.min(canvasWidth / vbW, FIT_MAX_HEIGHT / vbH)
    : 1;
  const svgW = Math.floor(vbW * fitScale * zoom);
  const svgH = Math.floor(vbH * fitScale * zoom);
  const zoomPct = Math.round(zoom * 100);
  const zoomOut = () => setZoom(prev => clampZoom(prev - ZOOM_STEP));
  const zoomIn = () => setZoom(prev => clampZoom(prev + ZOOM_STEP));
  const resetZoom = () => setZoom(1);

  return (
    <div className="kg-viewer">
      <div className="kg-viewer-toolbar" aria-label="지식 그래프 확대 컨트롤">
        <button
          type="button"
          className="kg-zoom-btn"
          onClick={zoomOut}
          disabled={zoom <= MIN_ZOOM}
          aria-label="축소"
          title="축소"
        >
          −
        </button>
        <span className="kg-zoom-value" aria-label={`확대 비율 ${zoomPct}%`}>
          {zoomPct}%
        </span>
        <button
          type="button"
          className="kg-zoom-btn"
          onClick={zoomIn}
          disabled={zoom >= MAX_ZOOM}
          aria-label="확대"
          title="확대"
        >
          +
        </button>
        <button
          type="button"
          className="kg-zoom-btn"
          onClick={resetZoom}
          disabled={zoom === 1}
          aria-label="확대 초기화"
          title="확대 초기화"
        >
          ↺
        </button>
      </div>
      <div className="kg-viewer-canvas" ref={canvasRef}>
        <svg
          className="kg-svg"
          width={svgW}
          height={svgH}
          viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            <marker id="arr" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L0,6 L6,3 z" fill="#cbd5e1"/>
            </marker>
            <marker id="arr-active" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L0,6 L6,3 z" fill="#4f6ef7"/>
            </marker>
            {nodes.filter(n => n.status !== 'missing' && n.status !== 'reference').map(n => (
              <filter key={n.id} id={`g${n.id}`} x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="3" result="blur"/>
                <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
            ))}
          </defs>

          {edges.map((e, i) => {
            const s = nodes.find(n => n.id === e.from);
            const t = nodes.find(n => n.id === e.to);
            if (!s || !t) return null;
            const hl = hovered === s.id || hovered === t.id;
            return (
              <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                stroke={hl ? '#4f6ef7' : '#cbd5e1'}
                strokeWidth={hl ? 2 : 1.5}
                markerEnd={hl ? 'url(#arr-active)' : 'url(#arr)'}
                opacity={0.8}
              />
            );
          })}

          {nodes.map(n => {
            const color = STATUS_COLOR[n.status] || STATUS_COLOR.missing;
            const stroke = STATUS_STROKE[n.status] || STATUS_STROKE.missing;
            const isHov = hovered === n.id;
            const isSel = selectedNodeId === n.id;
            const isProgressNode = n.status !== 'missing' && n.status !== 'reference';
            const r = 26;
            return (
              <g key={n.id} transform={`translate(${n.x},${n.y})`}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onNodeClick && onNodeClick(n)}
                style={{ cursor: onNodeClick ? 'pointer' : 'default' }}>
                {isSel && (
                  <circle r={r + 11} fill="none"
                    stroke="#4f6ef7" strokeWidth={2} strokeDasharray="4 3" opacity={0.8}
                    style={{ transition: 'all 0.2s ease' }}/>
                )}
                {isProgressNode && (
                  <circle r={r + 7} fill={color} opacity={isHov ? 0.18 : 0.1}
                    style={{ transition: 'opacity 0.2s' }}/>
                )}
                <circle r={r} fill={color} stroke={stroke} strokeWidth={isHov || isSel ? 2.5 : 1.5}
                  filter={isProgressNode ? `url(#g${n.id})` : ''}
                  style={{ transition: 'all 0.3s ease' }}
                />
                <NodeLabel label={n.label} r={r}
                  fill={n.status === 'missing' ? '#94a3b8' : '#0f172a'}
                  fontWeight={isHov || isSel ? 700 : 500}
                  highlight={isHighImportance(n.importance)}
                />
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
