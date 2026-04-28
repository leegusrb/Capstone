import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import KnowledgeGraph from '../components/KnowledgeGraph';
import './UploadAnalysis.css';

const STEPS = [
  { id: 1, label: '텍스트 추출 중...', detail: 'PDF 파싱 및 구조 분석' },
  { id: 2, label: '벡터 DB 저장 중...', detail: '임베딩 생성 & 인덱싱' },
  { id: 3, label: '핵심 개념(Reference KG) 생성 중...', detail: 'GPT-4o로 지식 그래프 추출' },
];

const KG_NODES = [
  { id: 'ip',         label: 'IP',        x: 230, y: 55,  status: 'confirmed' },
  { id: 'tcp',        label: 'TCP',       x: 110, y: 140, status: 'confirmed' },
  { id: 'udp',        label: 'UDP',       x: 350, y: 140, status: 'confirmed' },
  { id: 'http',       label: 'HTTP',      x: 55,  y: 240, status: 'confirmed' },
  { id: 'tls',        label: 'TLS',       x: 170, y: 240, status: 'confirmed' },
  { id: 'flow',       label: '흐름제어',   x: 95,  y: 330, status: 'confirmed' },
  { id: 'congestion', label: '혼잡제어',   x: 220, y: 330, status: 'confirmed' },
  { id: 'ack',        label: 'ACK',       x: 340, y: 240, status: 'confirmed' },
  { id: 'handshake',  label: '3-way HS',  x: 420, y: 140, status: 'confirmed' },
  { id: 'dns',        label: 'DNS',       x: 440, y: 280, status: 'confirmed' },
];
const KG_EDGES = [
  { from:'ip',to:'tcp' },{ from:'ip',to:'udp' },
  { from:'tcp',to:'http' },{ from:'tcp',to:'tls' },
  { from:'tcp',to:'flow' },{ from:'tcp',to:'congestion' },
  { from:'tcp',to:'handshake' },{ from:'handshake',to:'ack' },
  { from:'udp',to:'dns' },{ from:'udp',to:'ack' },
];
const KEYWORDS = ['TCP','UDP','IP','HTTP','TLS/SSL','흐름 제어','혼잡 제어',
  '3-way Handshake','ACK/SYN','DNS','소켓','포트','MTU','RTT','Sliding Window'];

export default function UploadAnalysis() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState('idle');
  const [step, setStep] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState('');
  const fileRef = useRef();

  function startAnalysis(name) {
    setFileName(name); setPhase('processing'); setStep(1);
    setTimeout(() => setStep(2), 1400);
    setTimeout(() => setStep(3), 2900);
    setTimeout(() => setPhase('done'), 4800);
  }

  return (
    <div className="upload-page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">파일 업로드</h1>
          <p className="page-sub">PDF를 업로드하면 Reference Knowledge Graph가 자동 생성됩니다.</p>
        </div>
      </div>

      {/* IDLE */}
      {phase === 'idle' && (
        <div className="upload-idle fade-in">
          <div
            className={`dropzone ${dragOver ? 'over' : ''}`}
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if(f) startAnalysis(f.name); }}
            onClick={() => fileRef.current.click()}
          >
            <div className="dz-icon">📄</div>
            <p className="dz-title">PDF 파일을 여기에 드롭하거나 클릭해 선택하세요</p>
            <p className="dz-sub">지원 형식: PDF · 최대 50MB</p>
            <button className="btn btn-primary" onClick={e => { e.stopPropagation(); fileRef.current.click(); }}>
              파일 선택
            </button>
            <input ref={fileRef} type="file" accept=".pdf" style={{ display:'none' }}
              onChange={e => { const f = e.target.files[0]; if(f) startAnalysis(f.name); }}/>
          </div>

          <div className="sample-hint">
            <span className="tag tag-gray">💡 예시</span>
            <span>TCP/IP 교재, OS 강의자료, 데이터베이스 논문 등 어떤 기술 문서도 가능합니다.</span>
          </div>
        </div>
      )}

      {/* PROCESSING */}
      {phase === 'processing' && (
        <div className="upload-processing fade-in">
          <div className="file-chip">
            <span>📄</span>
            <span className="file-chip-name">{fileName}</span>
            <span className="tag tag-yellow">분석 중</span>
          </div>
          <div className="processing-layout">
            <div className="card steps-card">
              <div className="card-label">분석 진행 상황</div>
              {STEPS.map((s, i) => {
                const done = step > s.id, active = step === s.id;
                return (
                  <div key={s.id} className={`step-row ${done?'done':''} ${active?'active':''}`}>
                    <div className="step-icon-col">
                      <div className="step-circle">
                        {done ? '✓' : active ? <div className="spin-dot"/> : s.id}
                      </div>
                      {i < 2 && <div className="step-line"/>}
                    </div>
                    <div className="step-body">
                      <div className="step-name">{s.label}</div>
                      <div className="step-detail">{s.detail}</div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="card processing-placeholder">
              <div className="card-label">KG 생성 중...</div>
              <div className="placeholder-lines">
                {[0.7,0.45,0.9,0.55,0.8].map((w,i)=>(
                  <div key={i} className="ph-line" style={{ width:`${w*100}%`, animationDelay:`${i*0.12}s` }}/>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* DONE */}
      {phase === 'done' && (
        <div className="upload-done fade-in">
          <div className="done-header">
            <div className="done-check">✓</div>
            <div>
              <h2>분석 완료</h2>
              <p>{fileName} — Reference KG 생성됨</p>
            </div>
          </div>

          <div className="result-layout">
            <div className="card kg-result-card">
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:16 }}>
                <div>
                  <div className="card-label">Reference Knowledge Graph</div>
                  <p style={{ fontSize:13, color:'var(--text-secondary)' }}>
                    {KG_NODES.length}개 노드 · {KG_EDGES.length}개 엣지
                  </p>
                </div>
                <div style={{ display:'flex', gap:6 }}>
                  <span className="tag tag-green">● Confirmed</span>
                  <span className="tag tag-gray">● Missing</span>
                </div>
              </div>
              <div className="kg-bg">
                <KnowledgeGraph nodes={KG_NODES} edges={KG_EDGES} width={500} height={370}/>
              </div>
            </div>

            <div className="result-right">
              <div className="card keywords-card">
                <div className="card-label">핵심 키워드 ({KEYWORDS.length}개)</div>
                <div className="kw-wrap">
                  {KEYWORDS.map((k,i)=>(
                    <span key={i} className="kw-pill">{k}</span>
                  ))}
                </div>
              </div>

              <div className="card stats-card">
                <div className="card-label">분석 요약</div>
                {[
                  ['노드 수', `${KG_NODES.length}개`],
                  ['엣지 수', `${KG_EDGES.length}개`],
                  ['키워드', `${KEYWORDS.length}개`],
                  ['예상 세션', '3~5회'],
                ].map(([k,v])=>(
                  <div key={k} className="stat-row">
                    <span>{k}</span><strong>{v}</strong>
                  </div>
                ))}
              </div>

              {/* Two mode buttons */}
              <div className="mode-buttons">
                <button className="mode-btn student-mode-btn" onClick={() => navigate('/student')}>
                  <div className="mode-btn-icon">🎓</div>
                  <div className="mode-btn-text">
                    <div className="mode-btn-title">학생 모드 (Learner)</div>
                    <div className="mode-btn-sub">더 공부할게요 · Study More</div>
                  </div>
                </button>
                <button className="mode-btn teacher-mode-btn" onClick={() => navigate('/teacher')}>
                  <div className="mode-btn-icon">🧑‍🏫</div>
                  <div className="mode-btn-text">
                    <div className="mode-btn-title">선생님 모드 (Teacher)</div>
                    <div className="mode-btn-sub">이제 설명할게요 · Start Explaining</div>
                  </div>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
