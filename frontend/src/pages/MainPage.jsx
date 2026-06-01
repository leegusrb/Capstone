import { useNavigate } from "react-router-dom";
import { useEffect } from "react";
import "./MainPage.css";

function useReveal() {
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }),
      { threshold: 0.07, rootMargin: "0px 0px -40px 0px" },
    );
    document.querySelectorAll(".rv").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

const PAIN_ITEMS = [
  { e: "📖", t: "강의를 다 읽었는데\n막상 시험에서 막혔다" },
  { e: "🗣️", t: "설명하려니\n갑자기 말이 안 나왔다" },
  { e: "❓", t: "열심히 했는데\n뭘 모르는지조차 몰랐다" },
];

const CHAT_MSGS = [
  { r: "ai", t: "TCP에 대해 설명해주실 수 있나요?" },
  {
    r: "user",
    t: "TCP는 연결 지향 프로토콜로, 신뢰성 있는 데이터 전송을 보장합니다.",
  },
  {
    r: "ai",
    t: "연결 지향이 구체적으로 어떤 의미인지 더 설명해주실 수 있나요?",
  },
  { r: "user", t: "..." },
];

const KG_DATA = {
  edges: [
    [118, 28, 52, 102],
    [118, 28, 188, 102],
    [52, 102, 52, 166],
    [188, 102, 188, 166],
  ],
  nodes: [
    [118, 28, "TCP", "#4f6ef7", 0],
    [52, 102, "흐름제어", "#4f6ef7", 0.5],
    [188, 102, "혼잡제어", "#f59e0b", 1.0],
    [52, 166, "슬라이딩", "#475569", 1.5],
    [188, 166, "ACK", "#ef4444", 2.0],
  ],
};

export default function MainPage() {
  const navigate = useNavigate();
  useReveal();

  return (
    <div className="mp">
      {/* ══ HERO (dark) ════════════════════════════ */}
      <section className="hero">
        <div className="hero-orb o1" />
        <div className="hero-orb o2" />
        <div className="hero-grid">
          <div className="hero-left">
            <div className="hero-enter" style={{ "--d": "0ms" }}>
              <span className="eyebrow-pill">
                🎓 페인만 기법 기반 학습 서비스
              </span>
            </div>
            <h1 className="hero-h1 hero-enter" style={{ "--d": "80ms" }}>
              설명할 수 있어야
              <br />
              <span className="hero-em">진짜 아는 겁니다</span>
            </h1>
            <p className="hero-sub hero-enter" style={{ "--d": "160ms" }}>
              AI 학생에게 직접 개념을 설명하세요.
              <br />
              말하면서 내 빈틈이 보입니다.
            </p>
            <div className="hero-btns hero-enter" style={{ "--d": "220ms" }}>
              <button className="btn-start" onClick={() => navigate("/upload")}>
                지금 시작하기 <span className="btn-arr">→</span>
              </button>
              <button
                className="btn-ghost"
                onClick={() => navigate("/archive")}
              >
                나의 저장소
              </button>
            </div>
          </div>

          <div className="hero-right hero-enter" style={{ "--d": "160ms" }}>
            <div className="kg-dark-card">
              <div className="kdc-bar">
                <div className="kdc-dots">
                  <i />
                  <i />
                  <i />
                </div>
                <span>Knowledge Graph · 실시간 추적</span>
              </div>
              <svg width="248" height="198" viewBox="0 0 248 198">
                <defs>
                  <filter id="nglow">
                    <feGaussianBlur stdDeviation="4" result="b" />
                    <feMerge>
                      <feMergeNode in="b" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                  <marker
                    id="marr"
                    markerWidth="6"
                    markerHeight="6"
                    refX="5"
                    refY="3"
                    orient="auto"
                  >
                    <path d="M0,0.5 L5.5,3 L0,5.5Z" fill="#4f6ef766" />
                  </marker>
                </defs>
                {KG_DATA.edges.map(([x1, y1, x2, y2], i) => {
                  const dx = x2 - x1,
                    dy = y2 - y1,
                    len = Math.hypot(dx, dy),
                    r = 16,
                    ux = dx / len,
                    uy = dy / len;
                  return (
                    <line
                      key={i}
                      x1={x1 + ux * r}
                      y1={y1 + uy * r}
                      x2={x2 - ux * (r + 3)}
                      y2={y2 - uy * (r + 3)}
                      stroke="#4f6ef755"
                      strokeWidth="1.5"
                      strokeDasharray="5 3"
                      markerEnd="url(#marr)"
                      className="e-flow"
                      style={{ animationDelay: `${i * 0.2}s` }}
                    />
                  );
                })}
                {KG_DATA.nodes.map(([x, y, l, c, d]) => (
                  <g key={l} className="n-grp" style={{ "--nd": `${d}s` }}>
                    <circle
                      cx={x}
                      cy={y}
                      r={22}
                      fill={c}
                      opacity={0.1}
                      className="n-pulse"
                    />
                    <circle
                      cx={x}
                      cy={y}
                      r={15}
                      fill={c}
                      filter="url(#nglow)"
                      opacity={0.88}
                    />
                    <text
                      x={x}
                      y={y + 4}
                      textAnchor="middle"
                      fill="#fff"
                      fontSize="8"
                      fontWeight="700"
                    >
                      {String(l).slice(0, 5)}
                    </text>
                  </g>
                ))}
              </svg>
              <div className="kdc-legend">
                {[
                  ["#4f6ef7", "이해됨"],
                  ["#f59e0b", "부분적"],
                  ["#475569", "미학습"],
                  ["#ef4444", "오개념"],
                ].map(([c, t]) => (
                  <span key={t} style={{ color: c }}>
                    ● {t}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ══ WHY ════════════════════════════════════ */}
      <section className="why-sec">
        <div className="why-header rv">
          <p className="why-eyebrow">많은 학생들이 이런 말을 합니다</p>
          <h2 className="why-title">열심히 했는데<br /><span className="why-em">왜 막히지?</span></h2>
        </div>
        <div className="why-cards">
          {[
            {
              icon: (
                <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="6" y="8" width="20" height="26" rx="3" stroke="#818cf8" strokeWidth="2.2" fill="#eef2ff"/>
                  <line x1="10" y1="15" x2="22" y2="15" stroke="#818cf8" strokeWidth="2" strokeLinecap="round"/>
                  <line x1="10" y1="20" x2="22" y2="20" stroke="#818cf8" strokeWidth="2" strokeLinecap="round"/>
                  <line x1="10" y1="25" x2="17" y2="25" stroke="#818cf8" strokeWidth="2" strokeLinecap="round"/>
                  <circle cx="31" cy="31" r="7" fill="#818cf8"/>
                  <line x1="28.5" y1="31" x2="33.5" y2="31" stroke="white" strokeWidth="2.2" strokeLinecap="round"/>
                </svg>
              ),
              quote: "다 읽었는데\n막상 설명하려니 말이 안 나와",
              reason: "눈으로 훑은 지식은 내 것이 아닙니다. 입으로 설명해봐야 비로소 드러납니다.",
              color: "#818cf8",
              bg: "#eef2ff",
            },
            {
              icon: (
                <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="20" cy="20" r="13" stroke="#f472b6" strokeWidth="2.2" fill="#fdf2f8"/>
                  <path d="M16 16.5c0-2.2 1.8-4 4-4s4 1.8 4 4c0 1.8-1.2 2.8-2.4 3.6C20.4 20.8 20 21.4 20 22.5" stroke="#f472b6" strokeWidth="2.2" strokeLinecap="round"/>
                  <circle cx="20" cy="27" r="1.3" fill="#f472b6"/>
                </svg>
              ),
              quote: "열심히 했는데\n내가 뭘 모르는지도 모르겠어",
              reason: "어디서 막히는지 모르면 무엇을 더 공부해야 할지도 알 수 없습니다.",
              color: "#f472b6",
              bg: "#fdf2f8",
            },
            {
              icon: (
                <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M8 10C8 8.9 8.9 8 10 8h20c1.1 0 2 .9 2 2v14c0 1.1-.9 2-2 2H22l-6 5v-5h-6c-1.1 0-2-.9-2-2V10z" stroke="#34d399" strokeWidth="2.2" fill="#ecfdf5"/>
                  <line x1="18" y1="17" x2="22" y2="21" stroke="#34d399" strokeWidth="2.2" strokeLinecap="round"/>
                  <line x1="22" y1="17" x2="18" y2="21" stroke="#34d399" strokeWidth="2.2" strokeLinecap="round"/>
                </svg>
              ),
              quote: "틀려도 아무도\n말 안 해주니까 그냥 넘어가",
              reason: "잘못된 이해가 시험 직전까지 발견되지 않고 쌓입니다.",
              color: "#34d399",
              bg: "#ecfdf5",
            },
          ].map(({ icon, quote, reason, color, bg }, i) => (
            <div
              key={i}
              className="why-card rv"
              style={{ "--wc": color, "--wb": bg, transitionDelay: `${i * 110}ms` }}
            >
              <div className="why-icon">{icon}</div>
              <p className="why-quote">"{quote}"</p>
              <p className="why-reason">{reason}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ══ FEATURES ═══════════════════════════════ */}
      <section className="feat-sec">
        {/* Feature 1 — large hero card */}
        <div className="feat-hero-card rv">
          <div className="fhc-text">
            <span className="feat-tag">핵심 차별점</span>
            <h2 className="fhc-title">
              AI가
              <br />
              진짜로 모릅니다
            </h2>
            <p className="fhc-desc">
              모르는 척이 아닙니다.
              <br />
              AI는 당신의 설명 전까지 아무것도 알지 못합니다.
              <br />
              설명할수록 AI의 지식이 채워지고, 당신의 빈틈이 드러납니다.
            </p>
          </div>
          <div className="fhc-vis">
            <div className="chat-mock">
              <div className="chat-mock-bar">
                <div className="cm-dots">
                  <i />
                  <i />
                  <i />
                </div>
                <span>AI 학생과의 대화</span>
              </div>
              {CHAT_MSGS.map(({ r, t }, i) => (
                <div
                  key={i}
                  className={`cm-row ${r}`}
                  style={{ animationDelay: `${0.4 + i * 0.55}s` }}
                >
                  {r === "ai" && <div className="cm-av ai">🤖</div>}
                  <div className={`cm-bubble ${r}`}>{t}</div>
                  {r === "user" && <div className="cm-av usr">👤</div>}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Features 2 & 3 — side by side */}
        <div className="feat-pair">
          <div className="feat-card rv" style={{ transitionDelay: "80ms" }}>
            <div
              className="fc-icon"
              style={{ background: "#eef2ff", color: "#4f6ef7" }}
            >
              📊
            </div>
            <h3 className="fc-title">이해도가 눈에 보입니다</h3>
            <p className="fc-desc">
              설명할수록 지식 그래프가 채워집니다. 어떤 개념을 알고, 어디가
              빠졌는지 시각적으로 확인하세요.
            </p>
            <div className="fc-bars">
              {[
                ["#4f6ef7", "이해됨", "72%"],
                ["#f59e0b", "부분 이해", "45%"],
                ["#94a3b8", "미학습", "20%"],
              ].map(([c, l, w]) => (
                <div key={l} className="fc-bar-row">
                  <span className="fc-bar-lbl" style={{ color: c }}>
                    {l}
                  </span>
                  <div className="fc-bar-track">
                    <div
                      className="fc-bar-fill"
                      style={{ "--c": c, "--w": w }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="feat-card rv" style={{ transitionDelay: "160ms" }}>
            <div
              className="fc-icon"
              style={{ background: "#faf5ff", color: "#8b5cf6" }}
            >
              🔄
            </div>
            <h3 className="fc-title">학습이 끊기지 않습니다</h3>
            <p className="fc-desc">
              오늘 못 다룬 개념은 다음 세션에서 이어집니다. 세션이 끝나도 학습
              맥락이 사라지지 않습니다.
            </p>
            <div className="fc-sessions">
              {[
                ["1회차", "40%", "0ms"],
                ["2회차", "65%", "150ms"],
                ["3회차", "88%", "300ms"],
              ].map(([s, w, d]) => (
                <div key={s} className="fc-sess-row">
                  <span className="fc-sess-lbl">{s}</span>
                  <div className="fc-sess-track">
                    <div
                      className="fc-sess-fill"
                      style={{ "--w": w, "--d": d }}
                    />
                  </div>
                  <span className="fc-sess-pct">{w}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ══ KG MAP ═════════════════════════════════ */}
      <section className="kg-sec rv">
        <div className="kg-sec-header">
          <h2 className="kg-sec-title">이해를 지도로 그립니다</h2>
          <p className="kg-sec-sub">
            세션이 끝나면 내가 어떤 개념을 알고, 어디가 빠졌는지<br />
            지식 그래프로 한눈에 확인할 수 있습니다.
          </p>
        </div>
        <div className="kg-compare">
          <div className="kg-cmp-card">
            <div className="kg-cmp-label before">세션 시작 전</div>
            <svg width="240" height="190" viewBox="0 0 240 190">
              {[[120,24,60,90],[120,24,180,90],[60,90,60,156],[180,90,180,156]].map(([x1,y1,x2,y2],i)=>(
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#e2e8f0" strokeWidth="1.5" strokeDasharray="5 3"/>
              ))}
              {[[120,24,"TCP"],[60,90,"흐름제어"],[180,90,"혼잡제어"],[60,156,"슬라이딩"],[180,156,"ACK"]].map(([x,y,l])=>(
                <g key={l}>
                  <circle cx={x} cy={y} r={15} fill="#94a3b8" opacity={0.25}/>
                  <circle cx={x} cy={y} r={15} fill="none" stroke="#cbd5e1" strokeWidth="1.5"/>
                  <text x={x} y={y+4} textAnchor="middle" fill="#94a3b8" fontSize="7.5" fontWeight="700">{l}</text>
                </g>
              ))}
            </svg>
            <p className="kg-cmp-desc">모든 노드가 미학습 상태</p>
          </div>
          <div className="kg-arrow-col">
            <div className="kg-arrow-line"/>
            <span className="kg-arrow-txt">세션 후</span>
          </div>
          <div className="kg-cmp-card">
            <div className="kg-cmp-label after">세션 완료 후</div>
            <svg width="240" height="190" viewBox="0 0 240 190">
              <defs>
                <filter id="kglow2">
                  <feGaussianBlur stdDeviation="3" result="b"/>
                  <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
              </defs>
              {[[120,24,60,90],[120,24,180,90],[60,90,60,156],[180,90,180,156]].map(([x1,y1,x2,y2],i)=>(
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#c7d2fe" strokeWidth="1.5" strokeDasharray="5 3"/>
              ))}
              {[
                [120,24,"TCP","#10b981"],
                [60,90,"흐름제어","#10b981"],
                [180,90,"혼잡제어","#f59e0b"],
                [60,156,"슬라이딩","#94a3b8"],
                [180,156,"ACK","#ef4444"],
              ].map(([x,y,l,c])=>(
                <g key={l}>
                  <circle cx={x} cy={y} r={20} fill={c} opacity={0.12}/>
                  <circle cx={x} cy={y} r={15} fill={c} filter="url(#kglow2)" opacity={0.9}/>
                  <text x={x} y={y+4} textAnchor="middle" fill="#fff" fontSize="7.5" fontWeight="700">{l}</text>
                </g>
              ))}
            </svg>
            <p className="kg-cmp-desc">이해 상태가 색으로 표시됨</p>
          </div>
        </div>
        <div className="kg-states">
          {[
            ["#10b981","Confirmed","완전히 설명한 개념"],
            ["#f59e0b","Partial","일부만 설명한 개념"],
            ["#94a3b8","Missing","언급하지 못한 개념"],
            ["#ef4444","Misconception","잘못 설명한 개념"],
          ].map(([c,s,d])=>(
            <div key={s} className="kg-state-item">
              <span className="kg-state-dot" style={{background:c}}/>
              <div>
                <span className="kg-state-name">{s}</span>
                <span className="kg-state-desc">{d}</span>
              </div>
            </div>
          ))}
        </div>

        {/* 체크리스트 기능 강조 */}
        <div className="kg-checklist-block rv">
          <div className="kcb-left">
            <span className="kcb-tag">✅ 체크리스트</span>
            <h3 className="kcb-title">
              노드를 클릭하면<br />
              세부 항목까지 확인됩니다
            </h3>
            <p className="kcb-desc">
              각 개념마다 AI가 생성한 세부 체크리스트가 있습니다.<br />
              어떤 항목을 설명했고, 무엇이 빠졌는지 항목 단위로 추적됩니다.
            </p>
            <div className="kcb-pills">
              <span className="kcb-pill green">✓ 설명한 항목</span>
              <span className="kcb-pill red">✗ 빠진 항목</span>
              <span className="kcb-pill orange">⚠ 오개념 항목</span>
            </div>
          </div>
          <div className="kcb-right">
            <div className="checklist-mock">
              <div className="clm-header">
                <span className="clm-status-dot" style={{background:"#10b981"}}/>
                <span className="clm-node-name">TCP</span>
                <span className="clm-badge">Confirmed</span>
              </div>
              <div className="clm-items">
                {[
                  [true,  false, "3-way handshake 과정 설명됨"],
                  [true,  false, "연결 지향 프로토콜 개념"],
                  [false, false, "혼잡 제어 메커니즘 (누락)"],
                  [false, true,  "슬라이딩 윈도우 (오개념 감지)"],
                ].map(([met, mis], i) => (
                  <div key={i} className={`clm-item ${mis ? "contradict" : met ? "met" : "unmet"}`}>
                    <span className="clm-icon">{mis ? "⚠" : met ? "✓" : "✗"}</span>
                    <span className="clm-text">{[
                      "3-way handshake 과정 설명됨",
                      "연결 지향 프로토콜 개념",
                      "혼잡 제어 메커니즘 (누락)",
                      "슬라이딩 윈도우 (오개념 감지)",
                    ][i]}</span>
                  </div>
                ))}
              </div>
              <p className="clm-hint">💡 리포트에서 모든 노드의 체크리스트를 확인하세요</p>
            </div>
          </div>
        </div>
      </section>

      {/* ══ HOW IT WORKS ═══════════════════════════ */}
      <section className="how-sec">
        <div className="how-header rv">
          <h2 className="how-title">딱 세단계입니다</h2>
          <p className="how-sub">복잡한 설정 없이 PDF 한 장으로 시작하세요</p>
        </div>
        <div className="steps">
          {[
            {
              n: "01",
              icon: "📄",
              title: "PDF 업로드",
              desc: "강의 자료를 올리면 AI가 핵심 개념을 자동으로 파악합니다.",
            },
            {
              n: "02",
              icon: "🗣️",
              title: "설명하기",
              desc: "AI 학생에게 알고 있는 것을 자유롭게 말해보세요.",
            },
            {
              n: "03",
              icon: "📊",
              title: "리포트 확인",
              desc: "어디가 부족한지 한눈에 파악하고 다음 학습을 계획하세요.",
            },
          ].map(({ n, icon, title, desc }, i) => (
            <div
              key={n}
              className="step-wrap rv"
              style={{ transitionDelay: `${i * 100}ms` }}
            >
              {i > 0 && (
                <div className="step-conn">
                  <div className="conn-dot d1" />
                  <div className="conn-dot d2" />
                  <div className="conn-dot d3" />
                </div>
              )}
              <div className="step-card">
                <div className="step-num">{n}</div>
                <div className="step-icon">{icon}</div>
                <h3 className="step-title">{title}</h3>
                <p className="step-desc">{desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ══ CTA (dark) ═════════════════════════════ */}
      <section className="cta rv">
        <div className="cta-orb ca" />
        <div className="cta-orb cb" />
        <p className="cta-eye">지금 바로 시작하세요</p>
        <h2 className="cta-h2">
          설명하면서
          <br />
          진짜 실력을 확인하세요
        </h2>
        <p className="cta-sub">PDF 한 장으로 충분합니다</p>
        <button className="cta-btn" onClick={() => navigate("/upload")}>
          📄 PDF 업로드하기
        </button>
      </section>
    </div>
  );
}
