import { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import KnowledgeGraph from '../components/KnowledgeGraph';
import { api, layoutKGNodes, convertEdges } from '../api';
import './SessionReport.css';

const SCORE_LABELS = {
  concept:     '개념 커버리지',
  accuracy:    '정확성',
  logic:       '논리성',
  specificity: '구체성',
};

const STATUS_LABEL = {
  confirmed:    'Confirmed',
  partial:      'Partial',
  missing:      'Missing',
  misconception:'Misconception',
};

function RadarChart({ scores }) {
  const entries = Object.entries(scores).filter(([k]) => SCORE_LABELS[k]);
  if (entries.length === 0) return null;
  const cx = 110, cy = 110, r = 72;
  const n = entries.length;
  const pts = entries.map(([, val], i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    const ratio = val / 3; // 0~3 스케일
    return {
      x: cx + Math.cos(angle) * r * ratio,
      y: cy + Math.sin(angle) * r * ratio,
      lx: cx + Math.cos(angle) * (r + 26),
      ly: cy + Math.sin(angle) * (r + 26),
      label: SCORE_LABELS[entries[i][0]],
    };
  });
  const grids = [0.25, 0.5, 0.75, 1];
  return (
    <svg width={220} height={220} viewBox="0 0 220 220">
      {grids.map(f => {
        const gp = entries.map((_, i) => {
          const a = (i / n) * 2 * Math.PI - Math.PI / 2;
          return `${cx + Math.cos(a) * r * f},${cy + Math.sin(a) * r * f}`;
        }).join(' ');
        return <polygon key={f} points={gp} fill="none" stroke="#e2e8f0" strokeWidth={1} />;
      })}
      {entries.map((_, i) => {
        const a = (i / n) * 2 * Math.PI - Math.PI / 2;
        return <line key={i} x1={cx} y1={cy} x2={cx + Math.cos(a) * r} y2={cy + Math.sin(a) * r} stroke="#e2e8f0" strokeWidth={1} />;
      })}
      <polygon
        points={pts.map(p => `${p.x},${p.y}`).join(' ')}
        fill="rgba(79,110,247,0.15)" stroke="#4f6ef7" strokeWidth={2}
      />
      {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={4} fill="#4f6ef7" />)}
      {pts.map((p, i) => (
        <text key={i} x={p.lx} y={p.ly} textAnchor="middle" dominantBaseline="middle"
          fontSize="10" fill="#64748b" fontFamily="Inter,sans-serif">
          {p.label}
        </text>
      ))}
    </svg>
  );
}

export default function SessionReport() {
  const navigate = useNavigate();
  const { state } = useLocation();

  const document_id   = state?.document_id;
  const topic         = state?.topic || '학습 세션';
  const scores        = state?.scores || {};
  const total         = state?.total || 0;
  const coverage      = state?.coverage || {};
  const missingNodes  = state?.missing_nodes || [];
  const misconceptions= state?.misconceptions || [];
  const turnCount     = state?.turn_count || 0;

  const totalPct = Math.round((total / 12) * 100);
  const passed = totalPct >= 70;

  const [afterNodes, setAfterNodes]   = useState([]);
  const [afterEdges, setAfterEdges]   = useState([]);
  const [kgDims, setKgDims]           = useState({ width: 420, height: 310 });
  const [selectedNode, setSelectedNode] = useState(null);
  const checklistRef = useRef(null);

  useEffect(() => {
    if (!document_id) return;
    api.getUserKG(document_id).then(data => {
      const nodes = data.user_kg?.nodes || [];
      const edges = data.user_kg?.edges || [];
      setAfterEdges(convertEdges(edges));
      const laid = layoutKGNodes(nodes, edges, 420, 310);
      setAfterNodes(laid.nodes);
      setKgDims({ width: laid.width, height: laid.height });
    }).catch(() => {});
  }, [document_id]);

  // BEFORE: 동일 노드를 모두 missing으로
  const beforeNodes = afterNodes.map(n => ({ ...n, status: 'missing' }));

  const rubricScores = Object.entries(scores)
    .filter(([k]) => SCORE_LABELS[k])
    .map(([k, v]) => ({ label: SCORE_LABELS[k], score: v, max: 3 }));

  function handleNodeClick(node) {
    setSelectedNode(prev => prev?.id === node.id ? null : node);
    setTimeout(() => checklistRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 50);
  }

  return (
    <div className="report-page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">세션 리포트</h1>
          <p className="page-sub">{topic} · {turnCount}턴 완료</p>
        </div>
      </div>

      {/* 1. 점수 카드 */}
      <div className="card score-card">
        <div className="score-layout">
          <div className="radar-col">
            <div className="card-label">루브릭 4영역 분석</div>
            <RadarChart scores={scores} />
          </div>
          <div className="score-bars-col">
            {rubricScores.map((r, i) => (
              <div key={i} className="score-row">
                <span className="score-lbl">{r.label}</span>
                <div className="score-bar-wrap">
                  <div className="progress-bar" style={{ flex: 1 }}>
                    <div className="progress-fill" style={{ width: `${(r.score / r.max) * 100}%` }} />
                  </div>
                  <span className="score-num">{r.score}/3</span>
                </div>
              </div>
            ))}
          </div>
          <div className="total-col">
            <div className={`total-badge ${passed ? 'pass' : 'fail'}`}>
              <div className="total-num">{totalPct}</div>
              <div className="total-denom">/ 100</div>
              <div className={`pf-tag ${passed ? 'pass' : 'fail'}`}>
                {passed ? '✓ PASS' : '✗ FAIL'}
              </div>
            </div>
            <div className="meta-rows">
              <div className="meta-row"><span>메시지 수</span><strong>{turnCount * 2}회</strong></div>
              <div className="meta-row"><span>오개념</span><strong style={{ color: '#ef4444' }}>{misconceptions.length}개</strong></div>
              <div className="meta-row">
                <span>확인 노드</span>
                <strong style={{ color: '#10b981' }}>
                  {coverage.confirmed_count || 0}/{coverage.total_count || 0}개
                </strong>
              </div>
              <div className="meta-row">
                <span>커버리지</span>
                <strong>{(coverage.coverage_percent || 0).toFixed(1)}%</strong>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 2. KG 비교 */}
      <section>
        <h2 className="section-title">지식 그래프 비교</h2>
        <div className="kg-compare-row">
          <div className="card kg-cmp">
            <div className="cmp-badge before">BEFORE</div>
            <div className="kg-bg">
              <KnowledgeGraph nodes={beforeNodes} edges={afterEdges} width={kgDims.width} height={kgDims.height} />
            </div>
          </div>
          <div className="cmp-arrow">→</div>
          <div className="card kg-cmp">
            <div className="cmp-badge after">AFTER</div>
            <div className="kg-bg">
              <KnowledgeGraph
                nodes={afterNodes} edges={afterEdges} width={kgDims.width} height={kgDims.height}
                onNodeClick={handleNodeClick}
                selectedNodeId={selectedNode?.id}
              />
            </div>
            <div className="kg-legend">
              <span className="kl green">● Confirmed</span>
              <span className="kl yellow">● Partial</span>
              <span className="kl red">● Misconception</span>
              <span className="kl gray">● Missing</span>
            </div>
            <p className="kg-click-hint">💡 노드를 클릭하면 체크리스트를 확인할 수 있습니다</p>
          </div>
        </div>

        <div className="node-checklist-panel" ref={checklistRef}>
          {selectedNode ? (
            <div className="ncp-content">
              <div className="ncp-header">
                <div className="ncp-title-row">
                  <span className={`ncp-status-dot ${selectedNode.status}`} />
                  <span className="ncp-node-name">{selectedNode.label}</span>
                  <span className={`ncp-badge ${selectedNode.status}`}>
                    {STATUS_LABEL[selectedNode.status]}
                  </span>
                </div>
                <button className="ncp-close-btn" onClick={() => setSelectedNode(null)}>✕</button>
              </div>
              {selectedNode.status === 'missing' || !selectedNode.checklist?.length ? (
                <p className="ncp-missing-msg">이 노드는 세션에서 언급되지 않았습니다.</p>
              ) : (
                <div className="ncp-items">
                  {selectedNode.checklist.map((item, i) => {
                    const cls = item.contradicted ? 'contradicted' : item.met ? 'met' : 'unmet';
                    const icon = item.contradicted ? '⚠' : item.met ? '✓' : '✗';
                    return (
                      <div key={i} className={`ncp-item ${cls}`}>
                        <span className="ncp-check-icon">{icon}</span>
                        <div className="ncp-item-body">
                          <p className="ncp-item-text">{item.item}</p>
                          {item.source_quote && <p className="ncp-item-quote">"{item.source_quote}"</p>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ) : (
            <div className="ncp-empty-state">
              <span className="ncp-empty-arrow">↑</span>
              <p className="ncp-empty-text">
                AFTER 그래프의 노드를 클릭하면<br />해당 개념의 체크리스트를 확인할 수 있습니다
              </p>
            </div>
          )}
        </div>
      </section>

      {/* 3. 오개념 */}
      {misconceptions.length > 0 && (
        <section>
          <h2 className="section-title">발견된 오개념</h2>
          <div className="card misconceptions-list-card">
            {misconceptions.map((m, i) => (
              <div key={i} className="mc-list-item">
                <div className="mc-list-num">{i + 1}</div>
                <p className="mc-list-text">{m}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 4. 다음 학습 */}
      {missingNodes.length > 0 && (
        <section>
          <h2 className="section-title">다음 학습 추천</h2>
          <div className="card next-card">
            <div className="card-label">아직 발견하지 못한 지식 (Missing Nodes)</div>
            <p style={{ fontSize: 13, color: '#94a3b8', marginBottom: 14 }}>
              태그를 클릭하면 해당 주제로 새 세션을 시작합니다.
            </p>
            <div className="missing-tags">
              {missingNodes.map((tag, i) => (
                <button key={i} className="missing-tag"
                  onClick={() => navigate('/teacher', { state: { document_id, topic: tag } })}>
                  {tag}
                </button>
              ))}
            </div>
          </div>
        </section>
      )}

      <div className="report-footer">
        <button className="btn btn-secondary btn-lg"
          onClick={() => navigate('/teacher', { state: { document_id, topic } })}>
          ↩ 다시 선생님 모드
        </button>
        <button className="btn btn-ghost btn-lg" onClick={() => navigate('/archive')}>
          저장소로 이동
        </button>
      </div>
    </div>
  );
}
