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

function initialReportData(state) {
  return {
    document_id:    state?.document_id,
    topic:          state?.topic || '학습 세션',
    scores:         state?.scores || {},
    total:          state?.total || 0,
    coverage:       state?.coverage || {},
    missing_nodes:  state?.missing_nodes || [],
    misconceptions: state?.misconceptions || [],
    turn_count:     state?.turn_count || 0,
  };
}

function normalizeReportData(data, fallback) {
  return {
    document_id:    data?.document_id ?? fallback.document_id,
    topic:          data?.topic || fallback.topic || '학습 세션',
    scores:         data?.scores || fallback.scores || {},
    total:          data?.total ?? fallback.total ?? 0,
    coverage:       data?.coverage || fallback.coverage || {},
    missing_nodes:  data?.missing_nodes || fallback.missing_nodes || [],
    misconceptions: data?.misconceptions || fallback.misconceptions || [],
    turn_count:     data?.turn_count ?? fallback.turn_count ?? 0,
  };
}

function RadarChart({ scores }) {
  const entries = Object.entries(scores).filter(([k]) => SCORE_LABELS[k]);
  if (entries.length === 0) return null;
  const cx = 110, cy = 110, r = 72;
  const n = entries.length;
  const pts = entries.map(([, val], i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    const ratio = val / 3;
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
  const { state, search } = useLocation();
  const sessionId = new URLSearchParams(search).get('session_id') || state?.session_record_id;
  const [reportData, setReportData] = useState(() => initialReportData(state));

  const document_id    = reportData.document_id;
  const topic          = reportData.topic;
  const scores         = reportData.scores;
  const total          = reportData.total;
  const coverage       = reportData.coverage;
  const missingNodes   = reportData.missing_nodes;
  const misconceptions = reportData.misconceptions;
  const turnCount      = reportData.turn_count;
  const closingMessage = state?.closing_message || '';

  const totalPct = Math.round((total / 12) * 100);
  const passed = totalPct >= 80;

  const [beforeNodes, setBeforeNodes] = useState([]);
  const [beforeEdges, setBeforeEdges] = useState([]);
  const [afterNodes, setAfterNodes] = useState([]);
  const [afterEdges, setAfterEdges] = useState([]);
  const [kgDims, setKgDims]         = useState({ width: 420, height: 310 });
  const [selectedNode, setSelectedNode] = useState(null);
  const [expandedEvidenceKey, setExpandedEvidenceKey] = useState(null);
  const [kgLoading, setKgLoading]   = useState(Boolean(sessionId || document_id));
  const checklistRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const fallback = initialReportData(state);

    function applyGraphPair(beforeKg, afterKg) {
      const afterRawNodes = afterKg?.nodes || [];
      const afterRawEdges = afterKg?.edges || [];
      if (!afterRawNodes.length) {
        setBeforeNodes([]);
        setBeforeEdges([]);
        setAfterNodes([]);
        setAfterEdges([]);
        return;
      }

      const laid = layoutKGNodes(afterRawNodes, afterRawEdges, 420, 310);
      if (!laid?.nodes) return;

      const byId = Object.fromEntries(laid.nodes.map(node => [node.id, node]));
      const beforeRawNodes = beforeKg?.nodes?.length
        ? beforeKg.nodes
        : afterRawNodes.map(node => ({ ...node, status: 'missing', checklist: [] }));
      const beforeRawEdges = beforeKg?.edges?.length ? beforeKg.edges : afterRawEdges;

      const alignToAfterLayout = (node) => {
        const positioned = byId[node.id] || {};
        return {
          id: node.id,
          label: node.id,
          x: positioned.x ?? Math.round(laid.width / 2),
          y: positioned.y ?? Math.round(laid.height / 2),
          status: node.status || 'missing',
          checklist: node.checklist || [],
        };
      };

      setBeforeNodes(beforeRawNodes.map(alignToAfterLayout));
      setBeforeEdges(convertEdges(beforeRawEdges));
      setAfterNodes(laid.nodes);
      setAfterEdges(convertEdges(afterRawEdges));
      setKgDims({ width: laid.width, height: laid.height });
    }

    async function loadCurrentUserKG(documentId) {
      const data = await api.getUserKG(documentId);
      if (!cancelled) applyGraphPair(null, data.user_kg);
    }

    async function loadReport() {
      if (!sessionId && !fallback.document_id) return;
      setKgLoading(true);
      setSelectedNode(null);
      setExpandedEvidenceKey(null);

      try {
        if (sessionId) {
          const data = await api.getSessionReport(sessionId);
          if (cancelled) return;

          setReportData(normalizeReportData(data, fallback));
          if (data.user_kg_after?.nodes?.length) {
            applyGraphPair(data.user_kg_before, data.user_kg_after);
          } else if (data.document_id) {
            await loadCurrentUserKG(data.document_id);
          }
        } else {
          setReportData(fallback);
          await loadCurrentUserKG(fallback.document_id);
        }
      } catch {
        if (fallback.document_id) await loadCurrentUserKG(fallback.document_id);
      } finally {
        if (!cancelled) setKgLoading(false);
      }
    }

    loadReport();
    return () => { cancelled = true; };
  }, [sessionId, state]);

  const rubricScores = Object.entries(scores)
    .filter(([k]) => SCORE_LABELS[k])
    .map(([k, v]) => ({ label: SCORE_LABELS[k], score: v, max: 3 }));

  function handleNodeClick(node) {
    setExpandedEvidenceKey(null);
    setSelectedNode(prev => prev?.id === node.id ? null : node);
    setTimeout(() => checklistRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 50);
  }

  function handleCloseChecklist() {
    setSelectedNode(null);
    setExpandedEvidenceKey(null);
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
        {kgLoading ? (
          <p style={{ color: '#94a3b8', fontSize: 13 }}>KG 불러오는 중...</p>
        ) : (
          <div className="kg-compare-row">
            <div className="card kg-cmp">
              <div className="cmp-badge before">이전 세션 KG</div>
              <div className="kg-bg">
                <KnowledgeGraph nodes={beforeNodes} edges={beforeEdges} width={kgDims.width} height={kgDims.height} />
              </div>
            </div>
            <div className="cmp-arrow">→</div>
            <div className="card kg-cmp">
              <div className="cmp-badge after">현재 세션 종료 KG</div>
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
        )}

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
                <button className="ncp-close-btn" onClick={handleCloseChecklist}>✕</button>
              </div>
              {selectedNode.status === 'missing' || !selectedNode.checklist?.length ? (
                <p className="ncp-missing-msg">이 노드는 세션에서 언급되지 않았습니다.</p>
              ) : (
                <div className="ncp-items">
                  {selectedNode.checklist.map((item, i) => {
                    const cls = item.contradicted ? 'contradicted' : item.met ? 'met' : 'unmet';
                    const icon = item.contradicted ? '⚠' : item.met ? '✓' : '✗';
                    const evidenceKey = `${selectedNode.id}-${i}`;
                    const isEvidenceOpen = expandedEvidenceKey === evidenceKey;
                    const hasSourceQuote = Boolean(item.source_quote);
                    const hasPageNumber = item.page_number !== null && item.page_number !== undefined;
                    return (
                      <div key={i} className={`ncp-item ${cls}`}>
                        <span className="ncp-check-icon">{icon}</span>
                        <div className="ncp-item-body">
                          <div className="ncp-item-main">
                            <p className="ncp-item-text">{item.item}</p>
                            {hasSourceQuote && (
                              <button
                                className={`ncp-source-btn ${hasPageNumber ? '' : 'no-page'}`}
                                onClick={() => setExpandedEvidenceKey(isEvidenceOpen ? null : evidenceKey)}
                                aria-expanded={isEvidenceOpen}
                              >
                                {hasPageNumber ? `p.${item.page_number}` : '근거'}
                              </button>
                            )}
                          </div>
                          {isEvidenceOpen && hasSourceQuote && (
                            <div className="ncp-evidence">
                              <span className="ncp-evidence-label">
                                PDF 근거{hasPageNumber ? ` · p.${item.page_number}` : ''}
                              </span>
                              <p className="ncp-item-quote">"{item.source_quote}"</p>
                            </div>
                          )}
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
                현재 세션 종료 KG의 노드를 클릭하면<br />해당 개념의 체크리스트를 확인할 수 있습니다
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
        <button className="btn btn-primary btn-lg"
          onClick={() => navigate('/student', { state: { document_id, topic } })}>
          학생 모드로 질문하기
        </button>
        <button className="btn btn-ghost btn-lg" onClick={() => navigate('/archive')}>
          저장소로 이동
        </button>
      </div>
    </div>
  );
}
