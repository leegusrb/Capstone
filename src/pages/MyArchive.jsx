import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './MyArchive.css';

const INIT_FILES = [
  {
    id: 1, name: 'TCP/IP 네트워크 프로토콜',
    file: 'computer_network_ch4.pdf',
    date: '2025-04-05', sessions: 3,
    coverage: 62, color: '#4f6ef7',
    emoji: '🌐',
    sessionList: [
      { id: 'S1', label: '세션 1', date: '2025-04-05', score: 75, topic: 'TCP 흐름/혼잡 제어' },
      { id: 'S2', label: '세션 2', date: '2025-04-03', score: 68, topic: 'IP & UDP' },
      { id: 'S3', label: '세션 3', date: '2025-04-01', score: 82, topic: '3-way Handshake' },
    ],
  },
  {
    id: 2, name: '운영체제 프로세스 스케줄링',
    file: 'os_scheduling.pdf',
    date: '2025-04-02', sessions: 2,
    coverage: 45, color: '#10b981',
    emoji: '⚙️',
    sessionList: [
      { id: 'S1', label: '세션 1', date: '2025-04-02', score: 70, topic: '라운드 로빈 스케줄링' },
      { id: 'S2', label: '세션 2', date: '2025-03-30', score: 65, topic: '우선순위 스케줄링' },
    ],
  },
  {
    id: 3, name: 'B-Tree 인덱스 구조',
    file: 'db_btree_index.pdf',
    date: '2025-03-28', sessions: 4,
    coverage: 82, color: '#8b5cf6',
    emoji: '🗄️',
    sessionList: [
      { id: 'S1', label: '세션 1', date: '2025-03-28', score: 90, topic: 'B+Tree vs B-Tree' },
      { id: 'S2', label: '세션 2', date: '2025-03-26', score: 78, topic: '인덱스 검색 알고리즘' },
      { id: 'S3', label: '세션 3', date: '2025-03-24', score: 85, topic: '삽입 및 분할' },
      { id: 'S4', label: '세션 4', date: '2025-03-22', score: 72, topic: '페이지 구조' },
    ],
  },
];

export default function MyArchive() {
  const navigate = useNavigate();
  const [files, setFiles] = useState(INIT_FILES);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(null);         // selected file id
  const [activeSession, setActiveSession] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editVal, setEditVal] = useState('');

  const filtered = files.filter(f =>
    f.name.toLowerCase().includes(search.toLowerCase()) ||
    f.file.toLowerCase().includes(search.toLowerCase())
  );

  const selectedFile = files.find(f => f.id === selected);

  function startEdit(f) {
    setEditingId(f.id);
    setEditVal(f.name);
  }
  function saveEdit(id) {
    if (editVal.trim()) {
      setFiles(prev => prev.map(f => f.id === id ? { ...f, name: editVal.trim() } : f));
    }
    setEditingId(null);
  }

  return (
    <div className="archive-page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">나의 학습 저장소</h1>
          <p className="page-sub">업로드한 자료와 세션 기록을 관리하세요.</p>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/upload')}>
          + 새 자료 업로드
        </button>
      </div>

      {/* Search */}
      <div className="search-bar-wrap">
        <div className="search-bar">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            placeholder="학습 자료 검색..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <button className="search-clear" onClick={() => setSearch('')}>✕</button>
          )}
        </div>
        <div className="search-count">
          {filtered.length}개의 자료
        </div>
      </div>

      <div className="archive-layout">
        {/* File list */}
        <div className="file-list">
          {filtered.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">📭</div>
              <p>검색 결과가 없습니다.</p>
            </div>
          ) : (
            filtered.map(f => (
              <div
                key={f.id}
                className={`file-card ${selected === f.id ? 'selected' : ''}`}
                onClick={() => { setSelected(f.id); setActiveSession(null); }}
              >
                <div className="file-card-top">
                  <div className="file-emoji" style={{ background: f.color + '18', border: `1.5px solid ${f.color}40` }}>
                    {f.emoji}
                  </div>
                  <div className="file-info">
                    {editingId === f.id ? (
                      <input
                        className="name-edit-input"
                        value={editVal}
                        autoFocus
                        onChange={e => setEditVal(e.target.value)}
                        onBlur={() => saveEdit(f.id)}
                        onKeyDown={e => { if(e.key==='Enter') saveEdit(f.id); if(e.key==='Escape') setEditingId(null); }}
                        onClick={e => e.stopPropagation()}
                      />
                    ) : (
                      <div className="file-name-row">
                        <span className="file-name">{f.name}</span>
                        <button
                          className="edit-btn"
                          title="이름 수정"
                          onClick={e => { e.stopPropagation(); startEdit(f); }}
                        >
                          ✏️
                        </button>
                      </div>
                    )}
                    <div className="file-meta">
                      <span>{f.file}</span>
                      <span>·</span>
                      <span>{f.date}</span>
                      <span>·</span>
                      <span>세션 {f.sessions}회</span>
                    </div>
                  </div>
                </div>

                <div className="file-coverage">
                  <div className="coverage-label">
                    <span>KG 커버리지</span>
                    <span style={{ color: f.color, fontWeight: 700 }}>{f.coverage}%</span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width:`${f.coverage}%`, background: f.color }}/>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Session detail panel */}
        <div className="session-panel">
          {!selectedFile ? (
            <div className="card session-placeholder">
              <div className="placeholder-icon">🗂️</div>
              <p>자료를 선택하면 세션별 대화 기록을 확인할 수 있습니다.</p>
            </div>
          ) : (
            <div className="card session-detail fade-in">
              <div className="session-detail-header">
                <div className="session-detail-emoji"
                  style={{ background: selectedFile.color + '18', border:`1.5px solid ${selectedFile.color}40` }}>
                  {selectedFile.emoji}
                </div>
                <div>
                  <h2 className="session-detail-name">{selectedFile.name}</h2>
                  <p style={{ fontSize:12, color:'#94a3b8' }}>{selectedFile.file}</p>
                </div>
              </div>

              {/* Session tabs */}
              <div className="session-tabs">
                {selectedFile.sessionList.map(s => (
                  <button
                    key={s.id}
                    className={`session-tab ${activeSession === s.id ? 'active' : ''}`}
                    onClick={() => setActiveSession(prev => prev === s.id ? null : s.id)}
                    style={activeSession === s.id ? { borderColor: selectedFile.color, color: selectedFile.color, background: selectedFile.color + '12' } : {}}
                  >
                    <span>{s.label}</span>
                    <span className="tab-score">{s.score}점</span>
                  </button>
                ))}
              </div>

              {/* Session conversation preview */}
              {activeSession && (() => {
                const sess = selectedFile.sessionList.find(s => s.id === activeSession);
                return (
                  <div className="session-preview slide-in">
                    <div className="session-preview-header">
                      <div>
                        <div className="session-topic">{sess.topic}</div>
                        <div className="session-date">{sess.date}</div>
                      </div>
                      <span className="tag tag-blue">점수 {sess.score}</span>
                    </div>

                    <div className="convo-preview">
                      <div className="convo-bubble ai">
                        <div className="convo-role">🤖 AI Student</div>
                        <p>{sess.topic}에 대해 설명해주세요! 저는 아직 이 개념이 낯설어요.</p>
                      </div>
                      <div className="convo-bubble user">
                        <div className="convo-role">👤 나</div>
                        <p>{sess.topic}은(는) ... (설명 내용 저장됨)</p>
                      </div>
                      <div className="convo-more">
                        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/teacher')}>
                          전체 대화 보기
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })()}

              <button className="btn btn-primary" style={{ width:'100%', justifyContent:'center', marginTop:16 }}
                onClick={() => navigate('/teacher')}>
                이 자료로 다시 학습하기
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
