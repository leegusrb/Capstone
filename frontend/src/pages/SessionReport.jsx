import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import KnowledgeGraph from '../components/KnowledgeGraph';
import './SessionReport.css';

const RUBRIC_SCORES = [
  { label: '개념 정확성', score: 8.5, max: 10 },
  { label: '설명 완성도', score: 7.0, max: 10 },
  { label: '예시 활용',   score: 6.5, max: 10 },
  { label: '논리 구조',   score: 8.0, max: 10 },
];
const TOTAL_SCORE = 75;
const PASSED = TOTAL_SCORE >= 70;

const BEFORE = [
  { id:'ip',label:'IP',x:200,y:40,status:'missing' },
  { id:'tcp',label:'TCP',x:100,y:120,status:'missing' },
  { id:'udp',label:'UDP',x:300,y:120,status:'missing' },
  { id:'flow',label:'흐름제어',x:60,y:220,status:'missing' },
  { id:'congestion',label:'혼잡제어',x:170,y:220,status:'missing' },
  { id:'handshake',label:'3-way HS',x:310,y:40,status:'missing' },
  { id:'ack',label:'ACK',x:340,y:180,status:'missing' },
];
const STATUS_LABEL = {
  confirmed: 'Confirmed',
  partial: 'Partial',
  missing: 'Missing',
  misconception: 'Misconception',
};

const AFTER = [
  {
    id:'ip', label:'IP', x:200, y:40, status:'confirmed',
    checklist: [
      { item:'IP가 비연결형 프로토콜임을 명시', source_quote:'IP는 패킷을 독립적으로 전달하는 비연결형 프로토콜이다.', met:true },
      { item:'라우팅 역할(경로 결정) 설명', source_quote:'IP는 패킷이 목적지까지 전달되는 경로를 결정한다.', met:true },
    ],
  },
  {
    id:'tcp', label:'TCP', x:100, y:120, status:'confirmed',
    checklist: [
      { item:'TCP가 연결 지향임을 명시', source_quote:'TCP는 연결 지향 프로토콜이다.', met:true },
      { item:'신뢰성 있는 데이터 전송 보장 설명', source_quote:'TCP는 패킷 손실 시 재전송을 통해 신뢰성을 보장한다.', met:true },
      { item:'순서 보장(시퀀스 번호) 언급', source_quote:'TCP는 시퀀스 번호로 패킷 순서를 보장한다.', met:true },
    ],
  },
  {
    id:'udp', label:'UDP', x:300, y:120, status:'partial',
    checklist: [
      { item:'UDP가 비연결형임을 명시', source_quote:'UDP는 연결 설정 없이 데이터를 전송한다.', met:true },
      { item:'신뢰성 없음(손실 허용) 특성 설명', source_quote:'UDP는 패킷 손실 시 재전송하지 않는다.', met:false },
      { item:'낮은 오버헤드로 인한 고속 전송 장점 설명', source_quote:'UDP는 TCP에 비해 오버헤드가 적어 실시간 애플리케이션에 적합하다.', met:false },
    ],
  },
  {
    id:'flow', label:'흐름제어', x:60, y:220, status:'misconception',
    checklist: [
      { item:'흐름 제어의 목적(수신측 버퍼 오버플로우 방지) 설명', source_quote:'흐름 제어는 수신자의 처리 속도에 맞게 송신 속도를 조절한다.', met:false, contradicted:true },
      { item:'슬라이딩 윈도우 메커니즘 언급', source_quote:'슬라이딩 윈도우를 사용해 수신 버퍼 크기에 따라 전송량을 제어한다.', met:false },
    ],
  },
  {
    id:'congestion', label:'혼잡제어', x:170, y:220, status:'partial',
    checklist: [
      { item:'혼잡 제어의 목적(네트워크 혼잡 방지) 설명', source_quote:'혼잡 제어는 네트워크 전체의 트래픽을 조절해 혼잡 붕괴를 방지한다.', met:true },
      { item:'AIMD 알고리즘 언급', source_quote:'혼잡 발생 시 전송 속도를 절반으로 줄이는 AIMD 방식을 사용한다.', met:false },
      { item:'혼잡 윈도우(CWND) 개념 설명', source_quote:'CWND는 네트워크 혼잡 상태에 따라 동적으로 조절되는 윈도우 크기다.', met:false },
    ],
  },
  {
    id:'handshake', label:'3-way HS', x:310, y:40, status:'confirmed',
    checklist: [
      { item:'SYN → SYN-ACK → ACK 순서 명시', source_quote:'TCP 연결은 SYN, SYN-ACK, ACK 세 단계로 수립된다.', met:true },
      { item:'연결 수립 목적(신뢰성 있는 채널 확보) 설명', source_quote:'3-way handshake는 양측이 데이터 전송 준비가 됐음을 확인한다.', met:true },
    ],
  },
  {
    id:'ack', label:'ACK', x:340, y:180, status:'confirmed',
    checklist: [
      { item:'ACK가 수신 확인 응답임을 설명', source_quote:'ACK는 수신자가 데이터를 정상적으로 받았음을 알리는 응답이다.', met:true },
      { item:'누적 ACK(Cumulative ACK) 개념 언급', source_quote:'누적 ACK는 그 이전까지의 모든 패킷을 수신했음을 나타낸다.', met:true },
    ],
  },
];
const KG_EDGES = [
  {from:'ip',to:'tcp'},{from:'ip',to:'udp'},
  {from:'tcp',to:'flow'},{from:'tcp',to:'congestion'},
  {from:'tcp',to:'handshake'},{from:'handshake',to:'ack'},
];

const MISCONCEPTIONS = [
  '흐름 제어를 "네트워크 혼잡 시 속도 감소"로 설명',
  'TCP의 ACK를 "수신 확인 신호"로만 설명',
];

const MISSING_NODES = [
  '#3-way_Handshake_세부_절차', '#Sliding_Window', '#TCP_타임아웃',
  '#UDP_특성', '#혼잡_윈도우(CWND)', '#AIMD_알고리즘',
];

function RadarChart({ scores }) {
  const cx = 110, cy = 110, r = 72;
  const n = scores.length;
  const pts = scores.map((s, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    const ratio = s.score / s.max;
    return {
      x: cx + Math.cos(angle) * r * ratio,
      y: cy + Math.sin(angle) * r * ratio,
      lx: cx + Math.cos(angle) * (r + 26),
      ly: cy + Math.sin(angle) * (r + 26),
      label: s.label,
    };
  });
  const grids = [0.25, 0.5, 0.75, 1];

  return (
    <svg width={220} height={220} viewBox="0 0 220 220">
      {grids.map(f => {
        const gp = scores.map((_, i) => {
          const a = (i / n) * 2 * Math.PI - Math.PI / 2;
          return `${cx + Math.cos(a) * r * f},${cy + Math.sin(a) * r * f}`;
        }).join(' ');
        return <polygon key={f} points={gp} fill="none" stroke="#e2e8f0" strokeWidth={1}/>;
      })}
      {scores.map((_, i) => {
        const a = (i / n) * 2 * Math.PI - Math.PI / 2;
        return <line key={i} x1={cx} y1={cy} x2={cx + Math.cos(a)*r} y2={cy + Math.sin(a)*r} stroke="#e2e8f0" strokeWidth={1}/>;
      })}
      <polygon
        points={pts.map(p => `${p.x},${p.y}`).join(' ')}
        fill="rgba(79,110,247,0.15)" stroke="#4f6ef7" strokeWidth={2}
      />
      {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={4} fill="#4f6ef7"/>)}
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
  const [selectedNode, setSelectedNode] = useState(null);
  const checklistRef = useRef(null);

  const handleNodeClick = (node) => {
    setSelectedNode(prev => prev?.id === node.id ? null : node);
    setTimeout(() => {
      checklistRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 50);
  };

  return (
    <div className="report-page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">세션 리포트</h1>
          <p className="page-sub">TCP 흐름 제어 & 혼잡 제어 · 2025년 4월 5일 · 10턴 완료</p>
        </div>
      </div>

      {/* 1. Score card */}
      <div className="card score-card">
        <div className="score-layout">
          <div className="radar-col">
            <div className="card-label">루브릭 4영역 분석</div>
            <RadarChart scores={RUBRIC_SCORES}/>
          </div>

          <div className="score-bars-col">
            {RUBRIC_SCORES.map((r, i) => (
              <div key={i} className="score-row">
                <span className="score-lbl">{r.label}</span>
                <div className="score-bar-wrap">
                  <div className="progress-bar" style={{ flex:1 }}>
                    <div className="progress-fill" style={{ width:`${(r.score/r.max)*100}%` }}/>
                  </div>
                  <span className="score-num">{r.score}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="total-col">
            <div className={`total-badge ${PASSED ? 'pass' : 'fail'}`}>
              <div className="total-num">{TOTAL_SCORE}</div>
              <div className="total-denom">/ 100</div>
              <div className={`pf-tag ${PASSED ? 'pass' : 'fail'}`}>
                {PASSED ? '✓ PASS' : '✗ FAIL'}
              </div>
            </div>
            <div className="meta-rows">
              <div className="meta-row"><span>소요 시간</span><strong>24분</strong></div>
              <div className="meta-row"><span>메시지 수</span><strong>18회</strong></div>
              <div className="meta-row"><span>오개념</span><strong style={{ color:'#ef4444' }}>{MISCONCEPTIONS.length}개</strong></div>
              <div className="meta-row"><span>확인 노드</span><strong style={{ color:'#10b981' }}>5/7개</strong></div>
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
            <div className="kg-bg"><KnowledgeGraph nodes={BEFORE} edges={KG_EDGES} width={380} height={270}/></div>
          </div>
          <div className="cmp-arrow">→</div>
          <div className="card kg-cmp">
            <div className="cmp-badge after">AFTER</div>
            <div className="kg-bg">
              <KnowledgeGraph
                nodes={AFTER} edges={KG_EDGES} width={380} height={270}
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
                  <span className={`ncp-status-dot ${selectedNode.status}`}/>
                  <span className="ncp-node-name">{selectedNode.label}</span>
                  <span className={`ncp-badge ${selectedNode.status}`}>
                    {STATUS_LABEL[selectedNode.status]}
                  </span>
                </div>
                <button className="ncp-close-btn" onClick={() => setSelectedNode(null)}>✕</button>
              </div>
              {selectedNode.status === 'missing' ? (
                <p className="ncp-missing-msg">이 노드는 세션에서 언급되지 않았습니다.</p>
              ) : (
                <div className="ncp-items">
                  {(selectedNode.checklist || []).map((item, i) => {
                    const cls = item.contradicted ? 'contradicted' : item.met ? 'met' : 'unmet';
                    const icon = item.contradicted ? '⚠' : item.met ? '✓' : '✗';
                    return (
                      <div key={i} className={`ncp-item ${cls}`}>
                        <span className="ncp-check-icon">{icon}</span>
                        <div className="ncp-item-body">
                          <p className="ncp-item-text">{item.item}</p>
                          <p className="ncp-item-quote">"{item.source_quote}"</p>
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
                AFTER 그래프의 노드를 클릭하면<br/>해당 개념의 체크리스트를 확인할 수 있습니다
              </p>
            </div>
          )}
        </div>
      </section>

      {/* 3. 오개념 목록 */}
      <section>
        <h2 className="section-title">발견된 오개념</h2>
        <div className="card misconceptions-list-card">
          {MISCONCEPTIONS.map((m, i) => (
            <div key={i} className="mc-list-item">
              <div className="mc-list-num">{i + 1}</div>
              <p className="mc-list-text">{m}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 4. 다음 학습 */}
      <section>
        <h2 className="section-title">다음 학습 추천</h2>
        <div className="card next-card">
          <div className="card-label">아직 발견하지 못한 지식 (Missing Nodes)</div>
          <p style={{ fontSize:13, color:'#94a3b8', marginBottom:14 }}>
            태그를 클릭하면 해당 주제로 새 세션을 시작합니다.
          </p>
          <div className="missing-tags">
            {MISSING_NODES.map((tag, i) => (
              <button key={i} className="missing-tag" onClick={() => navigate('/teacher')}>
                {tag}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <div className="report-footer">
        <button className="btn btn-secondary btn-lg" onClick={() => navigate('/teacher')}>
          ↩ 다시 선생님 모드
        </button>
        <button className="btn btn-ghost btn-lg" onClick={() => navigate('/')}>
          종료
        </button>
      </div>
    </div>
  );
}
