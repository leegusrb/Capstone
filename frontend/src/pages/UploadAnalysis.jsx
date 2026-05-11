import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import KnowledgeGraph from '../components/KnowledgeGraph';
import { api, layoutKGNodes, convertEdges } from '../api';
import './UploadAnalysis.css';

const STEPS = [
  { id: 1, label: '텍스트 추출 중...', detail: 'PDF 파싱 및 구조 분석' },
  { id: 2, label: '벡터 DB 저장 중...', detail: '임베딩 생성 & 인덱싱' },
  { id: 3, label: '핵심 개념(Reference KG) 생성 중...', detail: 'GPT-4o로 지식 그래프 추출' },
];

export default function UploadAnalysis() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState('idle');
  const [step, setStep] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState('');
  const [error, setError] = useState('');
  const [kgNodes, setKgNodes] = useState([]);
  const [kgEdges, setKgEdges] = useState([]);
  const [docInfo, setDocInfo] = useState(null); // { id, filename, chunk_count }
  const fileRef = useRef();

  async function startAnalysis(file) {
    if (phase !== 'idle') return; // 이중 실행 방지
    setFileName(file.name);
    setPhase('processing');
    setStep(1);
    setError('');

    // 단계 애니메이션 (업로드 완료 전까지 2, 3단계를 순차적으로 표시)
    const t1 = setTimeout(() => setStep(2), 4000);
    const t2 = setTimeout(() => setStep(3), 10000);

    try {
      const uploaded = await api.uploadDocument(file);
      clearTimeout(t1);
      clearTimeout(t2);
      setStep(3); // 완료 직전 3단계로

      // KG 데이터 가져오기
      const kgData = await api.getKG(uploaded.id);
      const refNodes = kgData.reference_kg?.nodes || [];
      const refEdges = kgData.reference_kg?.edges || [];

      setDocInfo({ id: uploaded.id, filename: uploaded.filename, chunk_count: uploaded.chunk_count });
      setKgEdges(convertEdges(refEdges));
      setKgNodes(layoutKGNodes(refNodes, refEdges, 560, 420));
      setPhase('done');
    } catch (e) {
      clearTimeout(t1);
      clearTimeout(t2);
      setError(e.message || '업로드 중 오류가 발생했습니다.');
      setPhase('idle');
    }
  }

  function handleFile(file) {
    if (!file) return;
    if (!file.name.endsWith('.pdf')) { setError('PDF 파일만 업로드 가능합니다.'); return; }
    startAnalysis(file);
  }

  const topic = docInfo ? docInfo.filename.replace(/\.pdf$/i, '') : '';
  const keywords = kgNodes.map(n => n.id).slice(0, 15);

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
          {error && <p style={{ color: '#ef4444', marginBottom: 12 }}>{error}</p>}
          <div
            className={`dropzone ${dragOver ? 'over' : ''}`}
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
            onClick={() => fileRef.current.click()}
          >
            <div className="dz-icon">📄</div>
            <p className="dz-title">PDF 파일을 여기에 드롭하거나 클릭해 선택하세요</p>
            <p className="dz-sub">지원 형식: PDF · 최대 20MB</p>
            <button className="btn btn-primary" onClick={e => { e.stopPropagation(); fileRef.current.click(); }}>
              파일 선택
            </button>
            <input ref={fileRef} type="file" accept=".pdf" style={{ display: 'none' }}
              onChange={e => handleFile(e.target.files[0])} />
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
                  <div key={s.id} className={`step-row ${done ? 'done' : ''} ${active ? 'active' : ''}`}>
                    <div className="step-icon-col">
                      <div className="step-circle">
                        {done ? '✓' : active ? <div className="spin-dot" /> : s.id}
                      </div>
                      {i < 2 && <div className="step-line" />}
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
                {[0.7, 0.45, 0.9, 0.55, 0.8].map((w, i) => (
                  <div key={i} className="ph-line" style={{ width: `${w * 100}%`, animationDelay: `${i * 0.12}s` }} />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* DONE */}
      {phase === 'done' && docInfo && (
        <div className="upload-done fade-in">
          <div className="done-header">
            <div className="done-check">✓</div>
            <div>
              <h2>분석 완료</h2>
              <p>{docInfo.filename} — Reference KG 생성됨</p>
            </div>
          </div>

          <div className="result-layout">
            <div className="card kg-result-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
                <div>
                  <div className="card-label">Reference Knowledge Graph</div>
                  <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                    {kgNodes.length}개 노드 · {kgEdges.length}개 엣지
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <span className="tag tag-blue">● 추출된 개념</span>
                </div>
              </div>
              <div className="kg-bg">
                <KnowledgeGraph nodes={kgNodes} edges={kgEdges} width={560} height={420} />
              </div>
            </div>

            <div className="result-right">
              <div className="card keywords-card">
                <div className="card-label">핵심 키워드 ({keywords.length}개)</div>
                <div className="kw-wrap">
                  {keywords.map((k, i) => (
                    <span key={i} className="kw-pill">{k}</span>
                  ))}
                </div>
              </div>

              <div className="card stats-card">
                <div className="card-label">분석 요약</div>
                {[
                  ['노드 수', `${kgNodes.length}개`],
                  ['엣지 수', `${kgEdges.length}개`],
                  ['청크 수', `${docInfo.chunk_count}개`],
                  ['키워드', `${keywords.length}개`],
                ].map(([k, v]) => (
                  <div key={k} className="stat-row">
                    <span>{k}</span><strong>{v}</strong>
                  </div>
                ))}
              </div>

              <div className="mode-buttons">
                <button className="mode-btn teacher-mode-btn"
                  onClick={() => navigate('/teacher', { state: { document_id: docInfo.id, topic, filename: docInfo.filename } })}>
                  <div className="mode-btn-icon">🧑‍🏫</div>
                  <div className="mode-btn-text">
                    <div className="mode-btn-title">선생님 모드 (Teacher)</div>
                    <div className="mode-btn-sub">이제 설명할게요 · Start Explaining</div>
                  </div>
                </button>
                <button className="mode-btn student-mode-btn"
                  onClick={() => navigate('/student', { state: { document_id: docInfo.id, topic, filename: docInfo.filename } })}>
                  <div className="mode-btn-icon">🎓</div>
                  <div className="mode-btn-text">
                    <div className="mode-btn-title">학생 모드 (Learner)</div>
                    <div className="mode-btn-sub">더 공부할게요 · Study More</div>
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
