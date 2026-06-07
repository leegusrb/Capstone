import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import './MyArchive.css';

const EMOJIS  = ['🌐', '⚙️', '🗄️', '📡', '🔬', '🧩', '📊', '💡'];
const COLORS   = ['#4f6ef7', '#10b981', '#8b5cf6', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];

function docColor(id)  { return COLORS[id % COLORS.length]; }
function docEmoji(id)  { return EMOJIS[id % EMOJIS.length]; }
function docName(filename) { return filename.replace(/\.pdf$/i, ''); }
function fmtDate(iso) {
  return new Date(iso).toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

export default function MyArchive() {
  const navigate = useNavigate();
  const [docs, setDocs]           = useState([]);
  const [sessions, setSessions]   = useState({}); // { [doc_id]: SessionRecord[] }
  const [selected, setSelected]   = useState(null);
  const [activeSession, setActiveSession] = useState(null);
  const [search, setSearch]       = useState('');
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError]         = useState('');

  useEffect(() => {
    api.getDocuments()
      .then(async data => {
        const doneDocs = data.filter(d => d.status === 'done');
        setDocs(doneDocs);
        const results = await Promise.allSettled(
          doneDocs.map(doc => api.getDocumentSessions(doc.id).then(s => [doc.id, s]))
        );
        const sessMap = {};
        results.forEach(r => {
          if (r.status === 'fulfilled') {
            const [id, s] = r.value;
            sessMap[id] = s;
          }
        });
        setSessions(sessMap);
      })
      .catch(e => setError(e.message || '문서 목록을 불러오지 못했습니다.'))
      .finally(() => setLoadingDocs(false));
  }, []);

  async function selectDoc(doc) {
    setSelected(doc.id);
    setActiveSession(null);
    if (sessions[doc.id]) return; // 이미 로드됨
    setLoadingSessions(true);
    try {
      const data = await api.getDocumentSessions(doc.id);
      setSessions(prev => ({ ...prev, [doc.id]: data }));
    } catch {
      setSessions(prev => ({ ...prev, [doc.id]: [] }));
    } finally {
      setLoadingSessions(false);
    }
  }

  const filtered = docs.filter(d =>
    docName(d.filename).toLowerCase().includes(search.toLowerCase()) ||
    d.filename.toLowerCase().includes(search.toLowerCase())
  );
  const selectedDoc  = docs.find(d => d.id === selected);
  const sessionList  = selected ? (sessions[selected] || []) : [];
  const latestCoverage = sessionList.length > 0
    ? Math.round(sessionList[0].coverage_percent || 0)
    : 0;

  function terminationLabel(reason) {
    const map = { score: '목표 달성', turn_limit: '턴 초과', repetition: '반복 한계', user: '직접 종료' };
    return map[reason] || reason || '-';
  }

  async function deleteDoc(event, doc) {
    event.stopPropagation();
    if (deletingId) return;

    const ok = window.confirm(
      `"${docName(doc.filename)}" 자료를 삭제할까요?\n해당 자료의 세션 기록과 지식 그래프도 함께 삭제됩니다.`
    );
    if (!ok) return;

    setDeletingId(doc.id);
    setError('');
    try {
      await api.deleteDocument(doc.id);
      setDocs(prev => prev.filter(d => d.id !== doc.id));
      setSessions(prev => {
        const next = { ...prev };
        delete next[doc.id];
        return next;
      });
      if (selected === doc.id) {
        setSelected(null);
        setActiveSession(null);
      }
    } catch (e) {
      setError(e.message || '자료 삭제에 실패했습니다.');
    } finally {
      setDeletingId(null);
    }
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

      <div className="search-bar-wrap">
        <div className="search-bar">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            placeholder="학습 자료 검색..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && <button className="search-clear" onClick={() => setSearch('')}>✕</button>}
        </div>
        <div className="search-count">{filtered.length}개의 자료</div>
      </div>

      {error && <p style={{ color: '#ef4444', marginBottom: 12 }}>{error}</p>}

      <div className="archive-layout">
        {/* 문서 목록 */}
        <div className="file-list">
          {loadingDocs ? (
            <div className="empty-state"><div className="empty-icon">⏳</div><p>불러오는 중...</p></div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">📭</div>
              <p>{search ? '검색 결과가 없습니다.' : '업로드된 자료가 없습니다.'}</p>
            </div>
          ) : (
            filtered.map(doc => {
              const color    = docColor(doc.id);
              const coverage = doc.id === selected ? latestCoverage
                : (sessions[doc.id]?.[0]?.coverage_percent || 0);
              return (
                <div
                  key={doc.id}
                  className={`file-card ${selected === doc.id ? 'selected' : ''}`}
                  onClick={() => selectDoc(doc)}
                >
                  <div className="file-card-top">
                    <div className="file-emoji" style={{ background: color + '18', border: `1.5px solid ${color}40` }}>
                      {docEmoji(doc.id)}
                    </div>
                    <div className="file-info">
                      <div className="file-name-row">
                        <span className="file-name">{docName(doc.filename)}</span>
                      </div>
                      <div className="file-meta">
                        <span>{doc.filename}</span>
                        <span>·</span>
                        <span>{fmtDate(doc.created_at)}</span>
                        <span>·</span>
                        <span>세션 {(sessions[doc.id] || []).length}회</span>
                      </div>
                    </div>
                    <button
                      className="file-delete-btn"
                      onClick={(event) => deleteDoc(event, doc)}
                      disabled={deletingId === doc.id}
                      title="자료 삭제"
                      aria-label={`${docName(doc.filename)} 삭제`}
                    >
                      {deletingId === doc.id ? '삭제 중' : '삭제'}
                    </button>
                  </div>
                  <div className="file-coverage">
                    <div className="coverage-label">
                      <span>KG 커버리지</span>
                      <span style={{ color, fontWeight: 700 }}>{Math.round(coverage)}%</span>
                    </div>
                    <div className="progress-bar">
                      <div className="progress-fill" style={{ width: `${coverage}%`, background: color }} />
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* 세션 상세 패널 */}
        <div className="session-panel">
          {!selectedDoc ? (
            <div className="card session-placeholder">
              <div className="placeholder-icon">🗂️</div>
              <p>자료를 선택하면 세션별 기록을 확인할 수 있습니다.</p>
            </div>
          ) : (
            <div className="card session-detail fade-in">
              <div className="session-detail-header">
                <div className="session-detail-emoji"
                  style={{ background: docColor(selectedDoc.id) + '18', border: `1.5px solid ${docColor(selectedDoc.id)}40` }}>
                  {docEmoji(selectedDoc.id)}
                </div>
                <div>
                  <h2 className="session-detail-name">{docName(selectedDoc.filename)}</h2>
                  <p style={{ fontSize: 12, color: '#94a3b8' }}>{selectedDoc.filename}</p>
                </div>
              </div>

              {loadingSessions ? (
                <p style={{ color: '#94a3b8', fontSize: 13 }}>세션 기록 불러오는 중...</p>
              ) : sessionList.length === 0 ? (
                <p style={{ color: '#94a3b8', fontSize: 13 }}>아직 세션 기록이 없습니다.</p>
              ) : (
                <>
                  <div className="session-tabs">
                    {sessionList.map((s, i) => (
                      <button
                        key={s.id}
                        className={`session-tab ${activeSession === s.id ? 'active' : ''}`}
                        onClick={() => setActiveSession(prev => prev === s.id ? null : s.id)}
                        style={activeSession === s.id
                          ? { borderColor: docColor(selectedDoc.id), color: docColor(selectedDoc.id), background: docColor(selectedDoc.id) + '12' }
                          : {}}
                      >
                        <span>세션 {sessionList.length - i}</span>
                        <span className="tab-score">{Math.round((s.total_score / 12) * 100)}점</span>
                      </button>
                    ))}
                  </div>

                  {activeSession && (() => {
                    const sess = sessionList.find(s => s.id === activeSession);
                    if (!sess) return null;
                    return (
                      <div className="session-preview slide-in">
                        <div className="session-preview-header">
                          <div>
                            <div className="session-topic">{sess.topic}</div>
                            <div className="session-date">{fmtDate(sess.created_at)}</div>
                          </div>
                          <span className="tag tag-blue">
                            {Math.round((sess.total_score / 12) * 100)}점
                          </span>
                        </div>
                        <div className="convo-preview">
                          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, color: '#64748b' }}>
                            <span>턴 수: <strong>{sess.turn_count}</strong></span>
                            <span>종료 사유: <strong>{terminationLabel(sess.termination_reason)}</strong></span>
                            <span>커버리지: <strong>{(sess.coverage_percent || 0).toFixed(1)}%</strong></span>
                            {sess.misconceptions?.length > 0 && (
                              <span>오개념: <strong style={{ color: '#ef4444' }}>{sess.misconceptions.length}개</strong></span>
                            )}
                          </div>
                          <button
                            className="btn btn-secondary btn-sm"
                            style={{ marginTop: 14 }}
                            onClick={() => navigate(`/report?session_id=${sess.id}`)}
                          >
                            리포트 보기
                          </button>
                        </div>
                      </div>
                    );
                  })()}
                </>
              )}

              <button
                className="btn btn-primary"
                style={{ width: '100%', justifyContent: 'center', marginTop: 16 }}
                onClick={() => navigate('/teacher', {
                  state: { document_id: selectedDoc.id, topic: docName(selectedDoc.filename) },
                })}
              >
                이 자료로 다시 학습하기
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
