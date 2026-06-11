import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { api, getMisconceptionText } from '../api';
import './ChatMode.css';
import './TeacherMode.css';

const MAX_TURNS = 10;

export default function TeacherMode() {
  const navigate = useNavigate();
  const { state } = useLocation();
  const document_id = state?.document_id;
  const topic = state?.topic || '학습 주제';

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [turns, setTurns] = useState(0);
  const [showAlert, setShowAlert] = useState(false);
  const [misconceptions, setMisconceptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sessionDone, setSessionDone] = useState(false);
  const [coverage, setCoverage] = useState(null);
  const pendingReportRef = useRef(null);

  const conversationHistory = useRef([]);
  const sessionHistory = useRef([]);
  const initialUserKG = useRef(null);
  const chatRef = useRef();
  const initialized = useRef(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);
  const [voiceStatus, setVoiceStatus] = useState('idle');
  const isRecording = voiceStatus === 'recording';
  const isTranscribing = voiceStatus === 'transcribing';

  const initSession = useCallback(async () => {
    try {
      const res = await api.startSession(document_id, topic);
      const t = now();
      const firstMsg = { role: 'ai', text: res.first_question, time: t };
      setMessages([firstMsg]);
      conversationHistory.current = [{ role: 'assistant', content: res.first_question }];
      initialUserKG.current = res.initial_user_kg || null;
    } catch (e) {
      setError(e.message || '세션 시작에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  }, [document_id, topic]);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    if (!document_id) {
      setError('학습 자료를 먼저 업로드해주세요.');
      setLoading(false);
      return;
    }
    initSession();
  }, [document_id, initSession]);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages, typing]);

  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state === 'recording') {
        mediaRecorderRef.current.onstop = null;
        mediaRecorderRef.current.stop();
      }
      stopVoiceStream();
    };
  }, []);

  async function send() {
    if (!input.trim() || typing || sessionDone) return;
    if (turns >= MAX_TURNS) { setShowAlert(true); return; }

    const t = now();
    const userText = input.trim();
    const newTurns = turns + 1;

    setMessages(m => [...m, { role: 'user', text: userText, time: t }]);
    setInput('');
    setTurns(newTurns);
    setTyping(true);

    conversationHistory.current = [...conversationHistory.current, { role: 'user', content: userText }];

    try {
      const res = await api.processTurn({
        document_id,
        topic,
        user_explanation: userText,
        conversation_history: conversationHistory.current,
        session_history: sessionHistory.current,
        turn_count: newTurns,
        initial_user_kg: initialUserKG.current,
      });

      sessionHistory.current = [...sessionHistory.current, res.scores];

      if (res.misconceptions?.length) {
        const newMc = res.misconceptions.map(m => ({ text: getMisconceptionText(m), time: t }));
        setMisconceptions(prev => [...prev, ...newMc]);
      }
      if (res.coverage) setCoverage(res.coverage);

      setTyping(false);

      if (res.is_session_done) {
        const closingText = res.closing_message || '수고하셨습니다! 세션을 종료합니다.';
        setMessages(m => [...m, { role: 'ai', text: closingText, time: t }]);
        conversationHistory.current = [...conversationHistory.current, { role: 'assistant', content: closingText }];
        pendingReportRef.current = res;
        setSessionDone(true);
      } else {
        const aiText = res.next_question || '계속 설명해주세요.';
        setMessages(m => [...m, { role: 'ai', text: aiText, time: t }]);
        conversationHistory.current = [...conversationHistory.current, { role: 'assistant', content: aiText }];
        if (newTurns >= MAX_TURNS) setShowAlert(true);
      }
    } catch (e) {
      setTyping(false);
      setMessages(m => [...m, { role: 'ai', text: `오류가 발생했습니다: ${e.message}`, time: t }]);
    }
  }

  async function handleEndSession() {
    if (sessionDone) return;
    setSessionDone(true);
    try {
      const res = await api.endSession({
        document_id,
        topic,
        session_history: sessionHistory.current,
        initial_user_kg: initialUserKG.current,
      });
      navigateToReport(res);
    } catch {
      navigateToReport(null);
    }
  }

  function navigateToReport(result) {
    const sessionId = result?.session_record_id;
    navigate(sessionId ? `/report?session_id=${sessionId}` : '/report', {
      state: {
        session_record_id: sessionId,
        document_id,
        topic,
        scores: result?.scores || {},
        total: result?.total || 0,
        session_summary: result?.session_summary || {},
        closing_message: result?.closing_message || '',
        coverage: result?.coverage || {},
        missing_nodes: result?.missing_nodes || [],
        misconceptions: misconceptions.map(m => m.text),
        turn_count: turns,
      },
    });
  }

  function now() {
    return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  }

  async function toggleVoice() {
    if (voiceStatus === 'recording') {
      mediaRecorderRef.current?.stop();
      return;
    }

    if (voiceStatus === 'transcribing') return;

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      alert('이 브라우저는 음성 녹음을 지원하지 않습니다. 최신 Chrome 또는 Safari를 사용해주세요.');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = getSupportedAudioMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

      streamRef.current = stream;
      audioChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      recorder.onstop = async () => {
        setVoiceStatus('transcribing');
        stopVoiceStream();

        const audioBlob = new Blob(audioChunksRef.current, {
          type: mimeType || 'audio/webm',
        });
        audioChunksRef.current = [];

        if (!audioBlob.size) {
          alert('녹음된 오디오가 없습니다. 다시 시도해주세요.');
          setVoiceStatus('idle');
          return;
        }

        try {
          const res = await api.transcribeAudio(audioBlob, topic);
          const transcript = res.text?.trim();
          if (transcript) {
            setInput(prev => prev ? `${prev} ${transcript}` : transcript);
          }
        } catch (e) {
          alert(e.message || '음성 인식에 실패했습니다.');
        } finally {
          mediaRecorderRef.current = null;
          setVoiceStatus('idle');
        }
      };

      recorder.onerror = () => {
        stopVoiceStream();
        setVoiceStatus('idle');
        alert('녹음 중 오류가 발생했습니다.');
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setVoiceStatus('recording');
    } catch (e) {
      stopVoiceStream();
      setVoiceStatus('idle');
      alert(e.message || '마이크 권한을 확인해주세요.');
    }
  }

  function stopVoiceStream() {
    streamRef.current?.getTracks().forEach(track => track.stop());
    streamRef.current = null;
  }

  function getSupportedAudioMimeType() {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
    return candidates.find(type => MediaRecorder.isTypeSupported(type)) || '';
  }

  if (error) {
    return (
      <div className="chat-page fade-in" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="card" style={{ padding: 32, textAlign: 'center' }}>
          <p style={{ color: '#ef4444', marginBottom: 16 }}>{error}</p>
          <button className="btn btn-primary" onClick={() => navigate('/upload')}>파일 업로드하러 가기</button>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-page fade-in">
      {showAlert && (
        <div className="turn-alert pop-in">
          <div className="alert-inner">
            <div className="alert-icon">📊</div>
            <div>
              <div className="alert-title">세션 완료!</div>
              <div className="alert-desc">
                {sessionDone ? '평가가 완료되었습니다.' : '10턴이 완료되었습니다.'} 리포트를 확인해보세요.
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, marginLeft: 'auto' }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowAlert(false)}>계속하기</button>
              <button className="btn btn-primary btn-sm" onClick={handleEndSession}>리포트 보기 →</button>
            </div>
          </div>
        </div>
      )}

      <div className="chat-topbar">
        <div className="chat-topbar-left">
          <div className="mode-icon teacher">🧑‍🏫</div>
          <div>
            <div className="mode-title">선생님 모드 (Teacher)</div>
            <div className="mode-subtitle">{topic} · AI 학생에게 직접 설명하며 이해도를 확인하세요</div>
          </div>
          <span className="tag tag-blue">설명 중</span>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <div className={`turn-counter ${turns >= MAX_TURNS ? 'maxed' : turns >= 7 ? 'warn' : ''}`}>
            <span className="turn-label">현재 턴</span>
            <span className="turn-num">{turns} / {MAX_TURNS}</span>
            <div className="turn-bar">
              <div className="turn-fill" style={{ width: `${(turns / MAX_TURNS) * 100}%` }} />
            </div>
          </div>
          <button className="btn btn-red" onClick={handleEndSession} disabled={sessionDone}>
            세션 종료 및 리포트 보기
          </button>
        </div>
      </div>

      <div className="teacher-layout">
        <div className="chat-body" style={{ flex: 1 }}>
          <div className="chat-messages" ref={chatRef}>
            {loading && (
              <div className="bubble-row ai">
                <div className="bubble-ava ai">🤖</div>
                <div className="bubble ai typing"><span /><span /><span /></div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`bubble-row ${m.role}`}>
                {m.role === 'ai' && <div className="bubble-ava ai">🤖</div>}
                <div className={`bubble ${m.role}`}>
                  <p>{m.text}</p>
                  <span className="btime">{m.time}</span>
                </div>
                {m.role === 'user' && <div className="bubble-ava user">나</div>}
              </div>
            ))}
            {typing && (
              <div className="bubble-row ai">
                <div className="bubble-ava ai">🤖</div>
                <div className="bubble ai typing"><span /><span /><span /></div>
              </div>
            )}
          </div>

          {sessionDone ? (
            <div style={{
              padding: '16px 20px',
              borderTop: '1px solid #e2e8f0',
              display: 'flex',
              justifyContent: 'center',
            }}>
              <button
                className="btn btn-primary"
                style={{ padding: '12px 32px', fontSize: 15, fontWeight: 700 }}
                onClick={() => navigateToReport(pendingReportRef.current)}
              >
                📊 리포트 확인하기
              </button>
            </div>
          ) : (
            <div className="chat-input-bar">
              <textarea
                className="chat-textarea"
                placeholder="개념을 AI 학생에게 설명해 보세요... (Enter: 전송, Shift+Enter: 줄바꿈)"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
                rows={2}
                disabled={loading}
              />
              <button
                className={`mic-btn${isRecording ? ' recording' : ''}${isTranscribing ? ' transcribing' : ''}`}
                onClick={toggleVoice}
                disabled={loading || isTranscribing}
                title={isTranscribing ? '음성 변환 중' : isRecording ? '음성 입력 중단' : '음성으로 입력'}
              >
                {isTranscribing ? '…' : isRecording ? '⏹' : '🎙️'}
              </button>
              <button className="btn btn-primary send-btn" onClick={send}
                disabled={!input.trim() || loading}>
                전송
              </button>
            </div>
          )}
        </div>

        <div className="evaluator-panel">
          <div className="card evaluator-card">
            <div className="eval-header">
              <div className="eval-icon">⚖️</div>
              <div>
                <div className="eval-name">Evaluator AI</div>
                <div className="eval-status">
                  <span className="eval-dot" />실시간 평가 중
                </div>
              </div>
            </div>
            {coverage && (
              <div style={{ marginTop: 12, padding: '8px 0', borderTop: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>KG 커버리지</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ flex: 1, background: '#e2e8f0', borderRadius: 4, height: 6 }}>
                    <div style={{ width: `${coverage.coverage_percent || 0}%`, background: '#10b981', borderRadius: 4, height: '100%', transition: 'width 0.5s' }} />
                  </div>
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#10b981' }}>
                    {Math.round(coverage.coverage_percent || 0)}%
                  </span>
                </div>
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
                  {coverage.confirmed_count || 0} / {coverage.total_count || 0} 개념 확인됨
                </div>
              </div>
            )}
          </div>

          {misconceptions.length > 0 && (
            <div className="card misconception-panel slide-in">
              <div className="card-label" style={{ color: '#ef4444' }}>⚠ 오개념 감지</div>
              {misconceptions.map((m, i) => (
                <div key={i} className="mc-item">
                  <div className="mc-dot" />
                  <div>
                    <p className="mc-text">{m.content || m.text || String(m)}</p>
                    {m.correction && (
                      <p style={{ fontSize: 11, color: '#10b981', marginTop: 2 }}>
                        ✓ {m.correction}
                      </p>
                    )}
                  </div>
                </div>
              ))}
              <p className="mc-note">상세 내용은 리포트에서 확인하세요</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
