import { useState } from 'react';

const STATUS_COLOR = {
  confirmed: '#10b981',
  partial: '#f59e0b',
  missing: '#cbd5e1',
  active: '#4f6ef7',
};
const STATUS_STROKE = {
  confirmed: '#059669',
  partial: '#d97706',
  missing: '#94a3b8',
  active: '#3451d1',
};

export default function KnowledgeGraph({ nodes, edges, width = 500, height = 340 }) {
  const [hovered, setHovered] = useState(null);
  if (!nodes || !edges) return null;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ overflow: 'visible' }}>
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
        const r = 14;
        return (
          <g key={n.id} transform={`translate(${n.x},${n.y})`}
            onMouseEnter={() => setHovered(n.id)}
            onMouseLeave={() => setHovered(null)}
            style={{ cursor: 'pointer' }}>
            {n.status !== 'missing' && (
              <circle r={r + 7} fill={color} opacity={isHov ? 0.18 : 0.1}
                style={{ transition: 'opacity 0.2s' }}/>
            )}
            <circle r={r} fill={color} stroke={stroke} strokeWidth={isHov ? 2.5 : 1.5}
              filter={n.status !== 'missing' ? `url(#g${n.id})` : ''}
              style={{ transition: 'all 0.3s ease' }}
            />
            <text y={r + 14} textAnchor="middle"
              fill={n.status === 'missing' ? '#94a3b8' : '#0f172a'}
              fontSize={10} fontFamily="Inter,sans-serif"
              fontWeight={isHov ? 700 : 500}
            >
              {n.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
