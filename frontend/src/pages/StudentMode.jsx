import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './ChatMode.css';

const INIT_MSG = {
  role: 'ai', time: '10:00',
  text: '안녕하세요! 저는 AI 튜터예요. TCP/IP 네트워크에 대해 궁금한 점을 편하게 물어보세요! 🎓',
};

const AI_RESPONSES = [
  'TCP와 UDP의 가장 큰 차이는 무엇인가요? 신뢰성 측면에서 설명해주세요.',
  '3-way Handshake에서 SYN, SYN-ACK, ACK 각각의 역할을 알 수 있을까요?',
  '흐름 제어(Flow Control)와 혼잡 제어(Congestion Control)의 차이를 예시와 함께 알려주실 수 있나요?',
  '슬라이딩 윈도우(Sliding Window) 방식이 어떻게 동작하는지 설명해주세요.',
  '좋은 설명 감사해요! ACK 번호가 "다음에 받을 바이트 번호"인 이유가 뭔가요?',
];

export default function StudentMode() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState([INIT_MSG]);
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [aiIdx, setAiIdx] = useState(0);
  const chatRef = useRef();

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages, typing]);

  function send() {
    if (!input.trim()) return;
    const t = new Date().toLocaleTimeString('ko-KR', { hour:'2-digit', minute:'2-digit' });
    setMessages(m => [...m, { role:'user', text: input, time: t }]);
    setInput('');
    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      setMessages(m => [...m, {
        role: 'ai', time: t,
        text: AI_RESPONSES[aiIdx % AI_RESPONSES.length],
      }]);
      setAiIdx(i => i + 1);
    }, 1200 + Math.random() * 600);
  }

  return (
    <div className="chat-page fade-in">
      <div className="chat-topbar">
        <div className="chat-topbar-left">
          <div className="mode-icon student">🎓</div>
          <div>
            <div className="mode-title">학생 모드 (Learner)</div>
            <div className="mode-subtitle">AI 튜터에게 질문하며 학습하세요</div>
          </div>
          <span className="tag tag-green">학습 중</span>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => navigate('/teacher')}
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
                <span className="btime">{m.time}</span>
              </div>
              {m.role === 'user' && <div className="bubble-ava user">K</div>}
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
            placeholder="질문을 입력하거나 답변을 작성하세요... (Enter: 전송)"
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
    </div>
  );
}
