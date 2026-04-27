import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './LoginModal.css';

export default function LoginModal({ onClose }) {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ id: '', password: '' });
  const [error, setError] = useState('');

  function handleChange(e) {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }));
    setError('');
  }

  function handleSubmit(e) {
    e.preventDefault();
    if (!form.id.trim() || !form.password) { setError('아이디와 비밀번호를 입력해주세요.'); return; }
    const result = login(form);
    if (result.ok) {
      onClose();
    } else {
      setError(result.msg);
    }
  }

  function goRegister() {
    onClose();
    navigate('/register');
  }

  return (
    <div className="modal-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-card">
        <button className="modal-close" onClick={onClose}>✕</button>

        <div className="modal-header">
          <div className="modal-logo">
            <svg width="28" height="28" viewBox="0 0 26 26" fill="none">
              <circle cx="13" cy="6" r="4" fill="#4f6ef7"/>
              <circle cx="6" cy="20" r="4" fill="#10b981"/>
              <circle cx="20" cy="20" r="4" fill="#8b5cf6"/>
              <line x1="13" y1="9.5" x2="7.5" y2="17" stroke="#c7d2fe" strokeWidth="1.8"/>
              <line x1="13" y1="9.5" x2="18.5" y2="17" stroke="#c7d2fe" strokeWidth="1.8"/>
              <line x1="9" y1="20" x2="17" y2="20" stroke="#c7d2fe" strokeWidth="1.8"/>
            </svg>
          </div>
          <h2 className="modal-title">로그인</h2>
          <p className="modal-sub">KG-Tutor에 오신 것을 환영합니다</p>
        </div>

        <form className="modal-form" onSubmit={handleSubmit} noValidate>
          <div className="field-group">
            <label className="field-label">아이디</label>
            <input
              className="field-input"
              type="text"
              name="id"
              placeholder="아이디 입력"
              value={form.id}
              onChange={handleChange}
              autoComplete="username"
              autoFocus
            />
          </div>

          <div className="field-group">
            <label className="field-label">비밀번호</label>
            <input
              className="field-input"
              type="password"
              name="password"
              placeholder="비밀번호 입력"
              value={form.password}
              onChange={handleChange}
              autoComplete="current-password"
            />
          </div>

          {error && <p className="modal-error">{error}</p>}

          <button type="submit" className="modal-btn">로그인</button>
        </form>

        <div className="modal-footer">
          <span>회원이 아니십니까?</span>
          <button className="modal-register-link" onClick={goRegister}>회원가입하기</button>
        </div>
      </div>
    </div>
  );
}
