import { useState } from 'react';

function splitLabel(label) {
  if (label.includes(' ')) return label.split(' ').slice(0, 2);
  if (label.length > 5) return [label.slice(0, 5), label.slice(5)];
  return [label];
}

function NodeLabel({ label, r, fill, fontWeight }) {
  const lines = splitLabel(label);
  return (
    <text textAnchor="middle" fill={fill} fontSize={10}
      fontFamily="Inter,sans-serif" fontWeight={fontWeight}>
      {lines.map((line, i) => (
        <tspan key={i} x={0} y={r + 13 + i * 12}>{line}</tspan>
      ))}
    </text>
  );
}

const STATUS_COLOR = {
  confirmed: '#10b981',
  partial: '#f59e0b',
  missing: '#cbd5e1',
  active: '#4f6ef7',
  misconception: '#ef4444',
};
const STATUS_STROKE = {
  confirmed: '#059669',
  partial: '#d97706',
  missing: '#94a3b8',
  active: '#3451d1',
  misconception: '#dc2626',
};

const VPAD_X = 35; // viewBox 좌우 여백 (레이블 잘림 방지)
const VPAD_Y = 20; // viewBox 상하 여백

export default function KnowledgeGraph({ nodes, edges, width = 500, height = 340, onNodeClick, selectedNodeId }) {
  const [hovered, setHovered] = useState(null);
  if (!nodes || !edges) return null;

  return (
    <svg
      width={width} height={height}
      viewBox={`${-VPAD_X} ${-VPAD_Y} ${width + VPAD_X * 2} ${height + VPAD_Y * 2}`}
      style={{ overflow: 'visible' }}
    >
      <defs>
        <marker id="arr" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L6,3 z" fill="#cbd5e1"/>
        </marker>
        <marker id="arr-active" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L6,3 z" fill="#4f6ef7"/>
        </marker>
        {nodes.filter(n => n.status !== 'missing').map(n => (
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
        const r = 12;
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
            {n.status !== 'missing' && (
              <circle r={r + 7} fill={color} opacity={isHov ? 0.18 : 0.1}
                style={{ transition: 'opacity 0.2s' }}/>
            )}
            <circle r={r} fill={color} stroke={stroke} strokeWidth={isHov || isSel ? 2.5 : 1.5}
              filter={n.status !== 'missing' ? `url(#g${n.id})` : ''}
              style={{ transition: 'all 0.3s ease' }}
            />
            <NodeLabel label={n.label} r={r}
              fill={n.status === 'missing' ? '#94a3b8' : '#0f172a'}
              fontWeight={isHov || isSel ? 700 : 500}
            />
          </g>
        );
      })}
    </svg>
  );
}
