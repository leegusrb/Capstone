import { useNavigate } from 'react-router-dom';
import './MainPage.css';

const FLOW_STEPS = [
  { icon: '📄', title: '자료 업로드', desc: 'PDF를 올리면 AI가 Reference KG를 자동 추출합니다.' },
  { icon: '🎓', title: '학생 모드', desc: 'AI 튜터에게 물어보며 개념을 학습합니다.' },
  { icon: '🧑‍🏫', title: '선생님 모드', desc: '직접 AI 학생에게 설명하며 이해도를 확인합니다.' },
  { icon: '📊', title: '리포트', desc: '루브릭 평가와 지식 그래프 변화를 확인합니다.' },
];

const TECH_BADGES = ['GPT-4o', 'LangChain', 'Pinecone', 'React', 'Knowledge Graph', '2-Agent System'];

export default function MainPage() {
  const navigate = useNavigate();

  return (
    <div className="main-page fade-in">
      {/* Hero */}
      <div className="hero-section">
        <div className="hero-content">
          <div className="hero-badge">
            <span className="tag tag-blue">🎓 캡스톤 프로젝트</span>
          </div>
          <h1 className="hero-title">
            설명하면서<br/>
            <span className="hero-highlight">진짜 이해</span>를 확인하세요
          </h1>
          <p className="hero-desc">
            AI 학생에게 직접 개념을 설명하고, Evaluator AI가 당신의 이해도를<br/>
            지식 그래프(Knowledge Graph)로 실시간 시각화합니다.
          </p>
          <div className="hero-actions">
            <button className="btn btn-primary btn-lg" onClick={() => navigate('/upload')}>
              지금 시작하기 →
            </button>
            <button className="btn btn-secondary btn-lg" onClick={() => navigate('/archive')}>
              나의 저장소 보기
            </button>
          </div>
        </div>

        {/* Visual */}
        <div className="hero-visual">
          <div className="kg-preview-card">
            <div className="kg-preview-label">Knowledge Graph</div>
            <svg width="240" height="180" viewBox="0 0 240 180">
              <defs>
                <filter id="glow-hero">
                  <feGaussianBlur stdDeviation="3" result="b"/>
                  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
              </defs>
              {[
                [120,30, 120,90], [120,90, 60,140], [120,90, 180,140],
                [60,140, 180,140],
              ].map(([x1,y1,x2,y2],i) => (
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#c7d2fe" strokeWidth="1.5"/>
              ))}
              {[
                [120,30,'TCP','#4f6ef7','confirmed'],
                [60,140,'흐름제어','#10b981','confirmed'],
                [180,140,'혼잡제어','#10b981','confirmed'],
                [120,90,'IP','#f59e0b','partial'],
              ].map(([x,y,label,color,status]) => (
                <g key={label}>
                  <circle cx={x} cy={y} r={18} fill={color} opacity={0.15}/>
                  <circle cx={x} cy={y} r={13} fill={color} filter="url(#glow-hero)"/>
                  <text x={x} y={y+4} textAnchor="middle" fill="#fff" fontSize="9" fontWeight="700">
                    {label.slice(0,4)}
                  </text>
                </g>
              ))}
            </svg>
            <div className="kg-legend-row">
              <span className="kleg green">● Confirmed</span>
              <span className="kleg yellow">● Partial</span>
              <span className="kleg gray">● Missing</span>
            </div>
          </div>
        </div>
      </div>

      {/* How it works */}
      <div className="how-section">
        <h2 className="section-title" style={{ textAlign: 'center', marginBottom: 32 }}>
          이렇게 동작합니다
        </h2>
        <div className="flow-steps">
          {FLOW_STEPS.map((step, i) => (
            <div key={i} className="flow-step">
              <div className="flow-num">{i + 1}</div>
              <div className="flow-icon">{step.icon}</div>
              <h3 className="flow-title">{step.title}</h3>
              <p className="flow-desc">{step.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Core concept */}
      <div className="concept-section">
        <div className="card concept-card">
          <div className="concept-text">
            <div className="tag tag-purple" style={{ marginBottom: 12 }}>🤖 2-Agent System</div>
            <h2 className="concept-title">Student AI + Evaluator AI</h2>
            <p className="concept-desc">
              <strong>Student AI</strong>는 아무것도 모르는 학생 역할로 질문을 던지며,
              <strong> Evaluator AI</strong>는 사용자의 설명을 분석해 루브릭 점수와 오개념을 평가합니다.
              두 AI의 협업으로 단순 암기가 아닌 <em>진짜 이해</em>를 측정합니다.
            </p>
            <div className="tech-badges">
              {TECH_BADGES.map(b => <span key={b} className="tech-badge">{b}</span>)}
            </div>
          </div>
          <div className="agent-diagram">
            <div className="agent-box student-agent">
              <div className="agent-icon">🤖</div>
              <div className="agent-name">Student AI</div>
              <div className="agent-role">질문 · 반응</div>
            </div>
            <div className="agent-arrows">
              <div className="arrow-label up">설명</div>
              <div className="bi-arrow"/>
              <div className="arrow-label down">질문</div>
            </div>
            <div className="agent-box user-agent">
              <div className="agent-icon">👤</div>
              <div className="agent-name">사용자</div>
              <div className="agent-role">선생님 역할</div>
            </div>
            <div className="evaluator-line"/>
            <div className="agent-box evaluator-agent">
              <div className="agent-icon">⚖️</div>
              <div className="agent-name">Evaluator AI</div>
              <div className="agent-role">실시간 채점</div>
            </div>
          </div>
        </div>
      </div>

      {/* CTA */}
      <div className="cta-section">
        <div className="card cta-card">
          <h2>지금 바로 시작해보세요</h2>
          <p>PDF 한 장으로 나만의 Knowledge Graph 학습을 시작할 수 있습니다.</p>
          <button className="btn btn-primary btn-lg" onClick={() => navigate('/upload')}>
            📄 PDF 업로드하기
          </button>
        </div>
      </div>
    </div>
  );
}
