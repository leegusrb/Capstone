import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './ChatMode.css';
import './TeacherMode.css';

const MAX_TURNS = 10;

const INIT_MSG = {
  role: 'ai', time: '10:24',
  text: '안녕하세요! 저는 지금 아무것도 모르는 상태입니다. TCP/IP 네트워크에 대해 편하게 설명해 주세요! 무엇부터 알려주실 건가요? 🤔',
};

const STUDENT_QUESTIONS = [
  'TCP가 연결 지향이라는 게 정확히 어떤 의미인가요?',
  '3-way Handshake에서 SYN → SYN-ACK → ACK가 각각 무슨 역할인지 설명해주실 수 있나요?',
  '흐름 제어와 혼잡 제어가 비슷하게 들리는데, 어떻게 다른가요?',
  'ACK 번호가 "다음에 받을 바이트 번호"라는 게 무슨 뜻인지 모르겠어요.',
  'UDP는 신뢰성이 없다고 하는데, 그럼 왜 사용하나요?',
  '슬라이딩 윈도우가 어떻게 흐름을 제어하는지 아직 잘 모르겠어요.',
  'TCP 세그먼트의 구조에 대해 더 자세히 알 수 있을까요?',
  'DNS는 어떤 계층에서 동작하나요?',
  '혼잡 회피(Congestion Avoidance)와 슬로우 스타트의 차이가 뭔가요?',
  '마지막으로, IP와 TCP가 협력하는 방식을 정리해줄 수 있나요?',
];

export default function TeacherMode() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState([INIT_MSG]);
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [turns, setTurns] = useState(0);
  const [showAlert, setShowAlert] = useState(false);
  const [misconceptions, setMisconceptions] = useState([]);
  const chatRef = useRef();

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages, typing]);

  function send() {
    if (!input.trim()) return;
    if (turns >= MAX_TURNS) { setShowAlert(true); return; }

    const t = new Date().toLocaleTimeString('ko-KR', { hour:'2-digit', minute:'2-digit' });
    const newTurns = turns + 1;
    setMessages(m => [...m, { role:'user', text: input, time: t }]);
    setInput('');
    setTurns(newTurns);

    // Occasional misconception detection
    const userText = input.toLowerCase();
    if (userText.includes('흐름') && userText.includes('네트워크')) {
      setMisconceptions(prev => [...prev, {
        text: '흐름 제어를 "네트워크 혼잡 관리"로 설명 — 실제로는 수신자 버퍼 기반 제어입니다.',
        time: t,
      }]);
    }

    if (newTurns >= MAX_TURNS) {
      setTimeout(() => setShowAlert(true), 1600);
    }

    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      setMessages(m => [...m, {
        role: 'ai', time: t,
        text: STUDENT_QUESTIONS[Math.min(newTurns - 1, STUDENT_QUESTIONS.length - 1)],
      }]);
    }, 1100 + Math.random() * 500);
  }

  return (
    <div className="chat-page fade-in">
      {/* 10턴 초과 알림 */}
      {showAlert && (
        <div className="turn-alert pop-in">
          <div className="alert-inner">
            <div className="alert-icon">📊</div>
            <div>
              <div className="alert-title">세션 완료!</div>
              <div className="alert-desc">10턴이 완료되었습니다. 리포트를 확인해보세요.</div>
            </div>
            <div style={{ display:'flex', gap:8, marginLeft:'auto' }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowAlert(false)}>계속하기</button>
              <button className="btn btn-primary btn-sm" onClick={() => navigate('/report')}>리포트 보기 →</button>
            </div>
          </div>
        </div>
      )}

      <div className="chat-topbar">
        <div className="chat-topbar-left">
          <div className="mode-icon teacher">🧑‍🏫</div>
          <div>
            <div className="mode-title">선생님 모드 (Teacher)</div>
            <div className="mode-subtitle">AI 학생에게 직접 설명하며 이해도를 확인하세요</div>
          </div>
          <span className="tag tag-blue">설명 중</span>
        </div>
        <div style={{ display:'flex', gap:10, alignItems:'center' }}>
          {/* Turn counter */}
          <div className={`turn-counter ${turns >= MAX_TURNS ? 'maxed' : turns >= 7 ? 'warn' : ''}`}>
            <span className="turn-label">현재 턴</span>
            <span className="turn-num">{turns} / {MAX_TURNS}</span>
            <div className="turn-bar">
              <div className="turn-fill" style={{ width:`${(turns/MAX_TURNS)*100}%` }}/>
            </div>
          </div>
          <button className="btn btn-red" onClick={() => navigate('/report')}>
            세션 종료 및 리포트 보기
          </button>
        </div>
      </div>

      <div className="teacher-layout">
        <div className="chat-body" style={{ flex:1 }}>
          <div className="chat-messages" ref={chatRef}>
            {messages.map((m, i) => (
              <div key={i} className={`bubble-row ${m.role}`}>
                {m.role === 'ai' && <div className="bubble-ava ai">🤖</div>}
                <div className={`bubble ${m.role}`}>
                  <p>{m.text}</p>
                  <span className="btime">{m.time}</span>
                </div>
                {m.role === 'user' && <div className="bubble-ava user">K</div>}
              </div>
            ))}
            {typing && (
              <div className="bubble-row ai">
                <div className="bubble-ava ai">🤖</div>
                <div className="bubble ai typing"><span/><span/><span/></div>
              </div>
            )}
          </div>

          <div className="chat-input-bar">
            <textarea
              className="chat-textarea"
              placeholder="개념을 AI 학생에게 설명해 보세요... (Enter: 전송, Shift+Enter: 줄바꿈)"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); send(); } }}
              rows={2}
            />
            <button className="btn btn-primary send-btn" onClick={send} disabled={!input.trim()}>
              전송
            </button>
          </div>
        </div>

        {/* Evaluator panel */}
        <div className="evaluator-panel">
          <div className="card evaluator-card">
            <div className="eval-header">
              <div className="eval-icon">⚖️</div>
              <div>
                <div className="eval-name">Evaluator AI</div>
                <div className="eval-status">
                  <span className="eval-dot"/>실시간 평가 중
                </div>
              </div>
            </div>
          </div>

          {misconceptions.length > 0 && (
            <div className="card misconception-panel slide-in">
              <div className="card-label" style={{ color:'#ef4444' }}>⚠ 오개념 감지</div>
              {misconceptions.map((m,i) => (
                <div key={i} className="mc-item">
                  <div className="mc-dot"/>
                  <div>
                    <p className="mc-text">{m.text}</p>
                    <span className="mc-time">{m.time}</span>
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
