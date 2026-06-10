import { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { api } from '../api';
import './ChatMode.css';

export default function StudentMode() {
  const navigate = useNavigate();
  const { state } = useLocation();
  const document_id = state?.document_id;
  const topic = state?.topic || '학습 주제';
  const filename = state?.filename;

  const [messages, setMessages] = useState(() => (
    document_id
      ? [{
          role: 'ai',
          time: now(),
          text: `안녕하세요! 저는 AI 튜터예요. ${topic}에 대해 궁금한 점을 편하게 물어보세요.`,
        }]
      : []
  ));
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [error, setError] = useState('');
  const chatRef = useRef();
  const conversationHistory = useRef([]);
  const recognitionRef = useRef(null);
  const [isRecording, setIsRecording] = useState(false);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages, typing]);

  function toggleVoice() {
    if (isRecording) {
      recognitionRef.current?.stop();
      setIsRecording(false);
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      alert('이 브라우저는 음성 인식을 지원하지 않습니다. Chrome을 사용해주세요.');
      return;
    }
    const recognition = new SR();
    recognition.lang = 'ko-KR';
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onstart = () => setIsRecording(true);
    recognition.onresult = (e) => {
      const transcript = e.results[0][0].transcript;
      setInput(prev => prev ? prev + ' ' + transcript : transcript);
    };
    recognition.onend = () => setIsRecording(false);
    recognition.onerror = () => setIsRecording(false);
    recognitionRef.current = recognition;
    recognition.start();
  }

  async function send() {
    if (!input.trim() || typing || !document_id) return;

    const t = now();
    const userText = input.trim();
    const previousHistory = conversationHistory.current;

    setMessages(m => [...m, { role: 'user', text: userText, time: t }]);
    setInput('');
    setTyping(true);
    setError('');

    try {
      const res = await api.askStudyTutor({
        document_id,
        topic,
        question: userText,
        conversation_history: previousHistory,
      });

      const aiMsg = {
        role: 'ai',
        time: now(),
        text: res.answer,
        sources: res.sources || [],
      };

      setTyping(false);
      setMessages(m => [...m, aiMsg]);
      conversationHistory.current = [
        ...previousHistory,
        { role: 'user', content: userText },
        { role: 'assistant', content: res.answer },
      ];
    } catch (e) {
      setTyping(false);
      const message = e.message || '답변 생성에 실패했습니다.';
      setError(message);
      setMessages(m => [...m, {
        role: 'ai',
        time: now(),
        text: `오류가 발생했습니다: ${message}`,
      }]);
    }
  }

  if (!document_id) {
    return (
      <div className="chat-page fade-in" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="card" style={{ padding: 32, textAlign: 'center' }}>
          <p style={{ color: '#ef4444', marginBottom: 16 }}>학습 자료를 먼저 업로드해주세요.</p>
          <button className="btn btn-primary" onClick={() => navigate('/upload')}>파일 업로드하러 가기</button>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-page fade-in">
      <div className="chat-topbar">
        <div className="chat-topbar-left">
          <div className="mode-icon student">🎓</div>
          <div>
            <div className="mode-title">학생 모드 (Learner)</div>
            <div className="mode-subtitle">
              {filename ? `${filename} · ` : ''}{topic} · AI 튜터에게 질문하며 학습하세요
            </div>
          </div>
          <span className="tag tag-green">학습 중</span>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => navigate('/teacher', { state: { document_id, topic, filename } })}
        >
          🧑‍🏫 선생님 모드로 전환 · Start Explaining
        </button>
      </div>

      <div className="chat-body">
        <div className="chat-messages" ref={chatRef}>
          {messages.map((m, i) => (
            <div key={i} className={`bubble-row ${m.role}`}>
              {m.role === 'ai' && <div className="bubble-ava ai">🎓</div>}
              <div className={`bubble ${m.role}`}>
                <p>{m.text}</p>
                {m.role === 'ai' && m.sources?.length > 0 && (
                  <div className="source-list">
                    {m.sources.map((source, idx) => (
                      <span key={idx} className="source-chip">
                        {formatSource(source)}
                      </span>
                    ))}
                  </div>
                )}
                <span className="btime">{m.time}</span>
              </div>
              {m.role === 'user' && <div className="bubble-ava user">나</div>}
            </div>
          ))}
          {typing && (
            <div className="bubble-row ai">
              <div className="bubble-ava ai">🎓</div>
              <div className="bubble ai typing">
                <span/><span/><span/>
              </div>
            </div>
          )}
        </div>

        <div className="chat-input-bar">
          <textarea
            className="chat-textarea"
            placeholder="궁금한 점을 입력하세요... (Enter: 전송, Shift+Enter: 줄바꿈)"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            rows={2}
            disabled={typing}
          />
          <button
            className={`mic-btn${isRecording ? ' recording' : ''}`}
            onClick={toggleVoice}
            disabled={typing}
            title={isRecording ? '음성 입력 중단' : '음성으로 입력'}
          >
            {isRecording ? '⏹' : '🎙️'}
          </button>
          <button className="btn btn-primary send-btn" onClick={send} disabled={!input.trim() || typing}>
            전송
          </button>
        </div>
        {error && <div className="chat-error">{error}</div>}
      </div>
    </div>
  );
}

function now() {
  return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}

function formatSource(source) {
  if (source.page_number != null) return `${source.page_number}페이지`;
  if (source.chunk_index != null) return `청크 ${source.chunk_index}`;
  return '자료';
}
