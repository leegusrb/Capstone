import { useNavigate } from 'react-router-dom';
import './MainPage.css';

/* ── 지금까지의 문제 ── */
const PROBLEMS = [
  {
    icon: '🤖',
    title: 'AI가 이미 다 알고 있어요',
    desc: '기존 AI 튜터는 "모르는 척"하지만, 사실 모든 답을 알고 있습니다. 학습자는 그냥 정답을 확인하는 셈이에요.',
  },
  {
    icon: '💬',
    title: '대화는 끝나면 사라집니다',
    desc: '매 세션이 독립적이라 오늘 배운 것이 내일 세션에 반영되지 않습니다. 항상 처음부터 시작해야 해요.',
  },
  {
    icon: '❓',
    title: '뭘 모르는지 모릅니다',
    desc: '공부를 마쳐도 어떤 개념이 부족한지, 어디서 오개념이 생겼는지 정량적으로 확인할 방법이 없어요.',
  },
  {
    icon: '📝',
    title: '이해했는지 확인이 주관적',
    desc: '스스로 "이해했다"고 느끼는 것과 실제로 설명할 수 있는 것은 다릅니다. 객관적 기준이 필요합니다.',
  },
];

/* ── 우리의 차별점 ── */
const DIFFS = [
  {
    label: 'AI가 진짜로 모릅니다',
    before: '기존: LLM이 모르는 척 — 사실 답을 알고 있음',
    after:  '우리: 컨텍스트 단계에서 차단 — Student AI가 진짜 무지 상태로 시작',
    color:  '#22d3ee',
  },
  {
    label: '이해도가 누적됩니다',
    before: '기존: 매 세션 독립, 오늘 배운 것 내일에 반영 안 됨',
    after:  '우리: Knowledge Graph가 세션을 넘어 이해도를 지속 추적',
    color:  '#4ade80',
  },
  {
    label: '학습자료 기반 평가',
    before: '기존: 평가 기준 없음 또는 주관적',
    after:  '우리: 업로드한 PDF 기반 루브릭 — 정확성·논리성·구체성 자동 채점',
    color:  '#a855f7',
  },
  {
    label: '설명이 학습이 됩니다',
    before: '기존: 읽고 → 이해한 척 → 다음 챕터',
    after:  '우리: 페인만 기법 — AI에게 설명하면서 진짜 이해를 검증',
    color:  '#fb7185',
  },
];

/* ── 작동 방식 (3단계) ── */
const HOW = [
  {
    step: '01',
    icon: '📄',
    title: 'PDF를 업로드하세요',
    desc:  '학습 자료를 올리면 AI가 핵심 개념 지식 그래프(Reference KG)를 자동 생성합니다. 어떤 개념을, 어느 정도 이해해야 하는지 기준이 만들어집니다.',
  },
  {
    step: '02',
    icon: '🗣️',
    title: 'AI 학생에게 설명하세요',
    desc:  '진짜로 아무것도 모르는 AI 학생에게 개념을 직접 설명합니다. 막히는 부분이 생기면 그게 바로 당신이 아직 이해하지 못한 부분입니다.',
  },
  {
    step: '03',
    icon: '📊',
    title: '이해도를 확인하세요',
    desc:  '설명이 끝나면 Knowledge Graph 커버리지, 루브릭 점수, 오개념 목록을 한눈에 볼 수 있습니다. 다음 세션에서 부족한 부분을 채워나갑니다.',
  },
];

/* ── KG 상태 ── */
const KG_STATES = [
  { color: '#4ade80', neon: 'rgba(74,222,128,0.35)',  label: 'Confirmed',     desc: '충분히 설명됨' },
  { color: '#fbbf24', neon: 'rgba(251,191,36,0.35)',   label: 'Partial',       desc: '부분적으로 설명됨' },
  { color: '#f87171', neon: 'rgba(248,113,113,0.35)',  label: 'Misconception', desc: '오개념 발견' },
  { color: '#475569', neon: 'rgba(71,85,105,0.2)',     label: 'Missing',       desc: '아직 언급 안 됨' },
];

export default function MainPage() {
  const navigate = useNavigate();

  return (
    <div className="main-page fade-in">

      {/* ════ HERO ════ */}
      <section className="mp-hero">
        <div className="mp-hero-glow mp-hero-glow-1" />
        <div className="mp-hero-glow mp-hero-glow-2" />
        <div className="mp-hero-glow mp-hero-glow-3" />

        <div className="mp-hero-inner">
          <div className="mp-hero-badge">
            <span className="mp-badge-dot" />
            2024 캡스톤디자인 · 페인만 기법 기반 자기주도학습
          </div>

          <h1 className="mp-hero-title">
            AI 학생에게 설명하며<br />
            <span className="mp-hero-shimmer">진짜 이해</span>를 확인하세요
          </h1>

          <p className="mp-hero-sub">
            읽고 끄덕이는 것과 설명할 수 있는 것은 다릅니다.<br />
            Knowledge Graph가 당신의 이해도를 세션마다 추적합니다.
          </p>

          <div className="mp-hero-actions">
            <button className="mp-btn-primary" onClick={() => navigate('/upload')}>
              지금 시작하기 →
            </button>
            <button className="mp-btn-ghost" onClick={() => navigate('/report')}>
              예시 리포트 보기
            </button>
          </div>
        </div>

        {/* 플로팅 KG 프리뷰 */}
        <div className="mp-hero-card">
          <div className="mp-hero-card-label">이해도 Knowledge Graph</div>
          <svg width="280" height="210" viewBox="0 0 280 210">
            <defs>
              <filter id="glow-h"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            </defs>
            {[[140,24,70,82],[140,24,210,82],[70,82,42,158],[70,82,140,158],[210,82,140,158],[210,82,238,158]].map(([x1,y1,x2,y2],i)=>(
              <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(255,255,255,0.12)" strokeWidth="1.5" strokeDasharray={i>=4?"5 4":""}/>
            ))}
            {[
              [140,24,'TCP/IP','#22d3ee'],
              [70,82,'흐름제어','#4ade80'],
              [210,82,'3-way HS','#4ade80'],
              [42,158,'슬라이딩','#fbbf24'],
              [140,158,'혼잡제어','#475569'],
              [238,158,'포트번호','#475569'],
            ].map(([x,y,label,color])=>(
              <g key={String(label)}>
                <circle cx={x} cy={y} r={22} fill={color} opacity={0.15}/>
                <circle cx={x} cy={y} r={15} fill={color} opacity={0.9} filter="url(#glow-h)"/>
                <text x={x} y={Number(y)+4} textAnchor="middle" fill="#fff" fontSize="7.5" fontWeight="800">{String(label).slice(0,5)}</text>
              </g>
            ))}
          </svg>
          <div className="mp-hero-card-legend">
            {KG_STATES.map(s=>(
              <span key={s.label} style={{color:s.color}}>● {s.label}</span>
            ))}
          </div>
          {/* 커버리지 바 */}
          <div className="mp-hero-coverage">
            <div className="mp-hero-coverage-label"><span>KG 커버리지</span><span style={{color:'#4ade80',fontWeight:800}}>57%</span></div>
            <div className="mp-hero-coverage-bar"><div style={{width:'57%'}} /></div>
          </div>
        </div>
      </section>

      {/* ════ 문제 제기 ════ */}
      <section className="mp-section mp-section-dark">
        <div className="mp-pain-layout">
          {/* 왼쪽: 큰 인트로 */}
          <div className="mp-pain-intro">
            <div className="mp-eyebrow mp-eyebrow-light" style={{marginBottom:20}}>지금까지의 문제</div>
            <h2 className="mp-title" style={{textAlign:'left', marginBottom:16}}>
              AI로 공부해도<br /><em>뭔가 부족한</em><br />이유가 있습니다
            </h2>
            <p className="mp-sub" style={{textAlign:'left'}}>
              도구가 없는 게 아닙니다.<br />진짜 이해를 <em style={{fontStyle:'normal',color:'#f87171'}}>검증</em>하는 도구가 없었던 겁니다.
            </p>
          </div>

          {/* 오른쪽: 공감 카드 */}
          <div className="mp-pain-cards">
            {PROBLEMS.map((p,i)=>(
              <div key={i} className="mp-pain-card">
                <span className="mp-pain-emoji">{p.icon}</span>
                <div>
                  <div className="mp-pain-title">{p.title}</div>
                  <div className="mp-pain-desc">{p.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ════ 차별점 ════ */}
      <section className="mp-section mp-section-offwhite">
        <div className="mp-section-head">
          <div className="mp-eyebrow">우리가 다른 이유</div>
          <h2 className="mp-title mp-title-dark"><em>4가지</em>가 근본적으로 다릅니다</h2>
          <p className="mp-sub mp-sub-dark">기능 하나 추가가 아니라, 학습 구조 자체를 바꿉니다.</p>
        </div>
        <div className="mp-vs-list">
          {DIFFS.map((d,i)=>(
            <div key={i} className="mp-vs-row" style={{'--accent':d.color}}>
              <div className="mp-vs-num">0{i+1}</div>
              <div className="mp-vs-label">{d.label}</div>
              <div className="mp-vs-before">
                <span className="mp-vs-tag-before">기존</span>
                <span>{d.before.replace('기존: ','')}</span>
              </div>
              <div className="mp-vs-arrow">→</div>
              <div className="mp-vs-after">
                <span className="mp-vs-tag-after">우리</span>
                <span>{d.after.replace('우리: ','')}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ════ 작동 방식 ════ */}
      <section className="mp-section mp-section-dark">
        <div className="mp-section-head">
          <div className="mp-eyebrow mp-eyebrow-light">어떻게 작동하나요</div>
          <h2 className="mp-title">딱 <em>3단계</em>입니다</h2>
          <p className="mp-sub">복잡한 설정 없이, PDF 하나로 시작할 수 있습니다.</p>
        </div>
        <div className="mp-how">
          {HOW.map((h,i)=>(
            <div key={i} className="mp-how-card">
              <div className="mp-how-step">{h.step}</div>
              {i < HOW.length-1 && <div className="mp-how-arrow">→</div>}
              <div className="mp-how-icon">{h.icon}</div>
              <h3>{h.title}</h3>
              <p>{h.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ════ KG 시각화 (차별점 심화) ════ */}
      <section className="mp-section mp-section-light">
        <div className="mp-section-head">
          <div className="mp-eyebrow">핵심 기술</div>
          <h2 className="mp-title mp-title-dark">이해도를 <em>지도로</em> 그립니다</h2>
          <p className="mp-sub mp-sub-dark">
            학습자료에서 추출한 기준 그래프와 사용자의 설명으로 만들어지는 동적 그래프를 비교해
            어떤 개념을 이해했고, 어디서 막혔는지 한눈에 볼 수 있습니다.
          </p>
        </div>

        <div className="mp-kg-visual">
          {/* Reference KG */}
          <div className="mp-kg-vis-card mp-kg-vis-ref">
            <div className="mp-kg-vis-label">
              <span className="mp-kg-badge mp-kg-ref">Reference KG</span>
              <span>학습자료 기반 정답 기준</span>
            </div>
            <svg width="100%" viewBox="0 0 260 160" style={{maxHeight:160}}>
              {[[130,20,65,70],[130,20,195,70],[65,70,35,130],[65,70,130,130],[195,70,130,130],[195,70,225,130]].map(([x1,y1,x2,y2],i)=>(
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#cbd5e1" strokeWidth="1.5"/>
              ))}
              {[[130,20,'TCP/IP'],[65,70,'흐름제어'],[195,70,'3-way'],[35,130,'슬라이딩'],[130,130,'혼잡제어'],[225,130,'포트번호']].map(([x,y,l])=>(
                <g key={String(l)}>
                  <circle cx={x} cy={y} r={18} fill="#475569" opacity={0.6}/>
                  <text x={x} y={Number(y)+4} textAnchor="middle" fill="#fff" fontSize="7" fontWeight="700">{String(l).slice(0,5)}</text>
                </g>
              ))}
            </svg>
            <div className="mp-kg-vis-sub">모든 노드가 Missing 상태 (세션 시작 전)</div>
          </div>

          <div className="mp-kg-vis-vs">
            <div className="mp-kg-vis-vs-line" />
            <div className="mp-kg-vis-vs-label">세션 후</div>
            <div className="mp-kg-vis-vs-line" />
          </div>

          {/* User KG */}
          <div className="mp-kg-vis-card mp-kg-vis-user">
            <div className="mp-kg-vis-label">
              <span className="mp-kg-badge mp-kg-user">User KG</span>
              <span>사용자 설명으로 채워진 이해도</span>
            </div>
            <svg width="100%" viewBox="0 0 260 160" style={{maxHeight:160}}>
              <defs><filter id="glow-kg"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
              {[[130,20,65,70],[130,20,195,70],[65,70,35,130],[65,70,130,130],[195,70,130,130],[195,70,225,130]].map(([x1,y1,x2,y2],i)=>(
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#cbd5e1" strokeWidth="1.5"/>
              ))}
              {[
                [130,20,'TCP/IP','#22d3ee'],
                [65,70,'흐름제어','#4ade80'],
                [195,70,'3-way','#4ade80'],
                [35,130,'슬라이딩','#fbbf24'],
                [130,130,'혼잡제어','#475569'],
                [225,130,'포트번호','#475569'],
              ].map(([x,y,l,c])=>(
                <g key={String(l)}>
                  <circle cx={x} cy={y} r={20} fill={c} opacity={0.15}/>
                  <circle cx={x} cy={y} r={14} fill={c} filter="url(#glow-kg)"/>
                  <text x={x} y={Number(y)+4} textAnchor="middle" fill="#fff" fontSize="7" fontWeight="700">{String(l).slice(0,5)}</text>
                </g>
              ))}
            </svg>
            <div className="mp-kg-vis-sub">4개 노드 확인, 2개 Missing → 다음 세션 목표</div>
          </div>
        </div>

        {/* 노드 상태 설명 */}
        <div className="mp-kg-states">
          {KG_STATES.map(s=>(
            <div key={s.label} className="mp-kg-state" style={{'--c':s.color,'--n':s.neon}}>
              <div className="mp-kg-dot" />
              <div className="mp-kg-state-label">{s.label}</div>
              <div className="mp-kg-state-desc">{s.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ════ CTA ════ */}
      <section className="mp-cta-section">
        <div className="mp-cta-border">
          <div className="mp-cta-inner">
            <div className="mp-cta-glow" />
            <div className="mp-eyebrow mp-eyebrow-light" style={{marginBottom:16}}>지금 바로 시작하세요</div>
            <h2 className="mp-cta-title">
              아는 것과 설명할 수 있는 것,<br />
              <span className="mp-hero-shimmer">차이를 확인해보세요</span>
            </h2>
            <p className="mp-cta-sub">
              PDF 하나만 있으면 됩니다.<br />학습자료 업로드 후 바로 시작할 수 있습니다.
            </p>
            <div className="mp-cta-actions">
              <button className="mp-btn-primary mp-btn-xl" onClick={() => navigate('/upload')}>
                📄 PDF 업로드로 시작하기
              </button>
              <button className="mp-btn-ghost mp-btn-xl" onClick={() => navigate('/report')}>
                리포트 예시 먼저 보기
              </button>
            </div>
          </div>
        </div>
      </section>

    </div>
  );
}
