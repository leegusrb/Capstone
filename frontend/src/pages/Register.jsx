import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './Register.css';

export default function Register() {
  const navigate = useNavigate();
  const { register, login } = useAuth();
  const [form, setForm] = useState({ id: '', password: '', name: '', email: '' });
  const [errors, setErrors] = useState({});
  const [done, setDone] = useState(false);

  function validate() {
    const e = {};
    if (!form.id.trim()) e.id = '아이디를 입력해주세요.';
    if (form.password.length < 6) e.password = '비밀번호는 6자 이상이어야 합니다.';
    if (!form.name.trim()) e.name = '이름을 입력해주세요.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) e.email = '올바른 이메일 형식이 아닙니다.';
    return e;
  }

  function handleChange(e) {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }));
    setErrors(prev => ({ ...prev, [e.target.name]: undefined }));
  }

  function handleSubmit(e) {
    e.preventDefault();
    const e2 = validate();
    if (Object.keys(e2).length > 0) { setErrors(e2); return; }
    const result = register(form);
    if (!result.ok) { setErrors({ id: result.msg }); return; }
    login({ id: form.id, password: form.password });
    setDone(true);
  }

  if (done) {
    return (
      <div className="register-wrap">
        <div className="register-card">
          <div className="register-success">
            <div className="success-icon">✓</div>
            <h2>회원가입 완료!</h2>
            <p><strong>{form.name}</strong>님, 환영합니다.</p>
            <button className="reg-btn" onClick={() => navigate('/')}>메인으로 이동</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="register-wrap">
      <div className="register-card">
        <div className="register-header">
          <div className="reg-logo">
            <svg width="32" height="32" viewBox="0 0 26 26" fill="none">
              <circle cx="13" cy="6" r="4" fill="#4f6ef7"/>
              <circle cx="6" cy="20" r="4" fill="#10b981"/>
              <circle cx="20" cy="20" r="4" fill="#8b5cf6"/>
              <line x1="13" y1="9.5" x2="7.5" y2="17" stroke="#c7d2fe" strokeWidth="1.8"/>
              <line x1="13" y1="9.5" x2="18.5" y2="17" stroke="#c7d2fe" strokeWidth="1.8"/>
              <line x1="9" y1="20" x2="17" y2="20" stroke="#c7d2fe" strokeWidth="1.8"/>
            </svg>
          </div>
          <h1 className="reg-title">회원가입</h1>
          <p className="reg-sub">KG-Tutor 계정을 만들어보세요</p>
        </div>

        <form className="reg-form" onSubmit={handleSubmit} noValidate>
          <div className="field-group">
            <label className="field-label">아이디</label>
            <input
              className={`field-input ${errors.id ? 'error' : ''}`}
              type="text"
              name="id"
              placeholder="사용할 아이디 입력"
              value={form.id}
              onChange={handleChange}
              autoComplete="username"
            />
            {errors.id && <span className="field-error">{errors.id}</span>}
          </div>

          <div className="field-group">
            <label className="field-label">비밀번호</label>
            <input
              className={`field-input ${errors.password ? 'error' : ''}`}
              type="password"
              name="password"
              placeholder="6자 이상 입력"
              value={form.password}
              onChange={handleChange}
              autoComplete="new-password"
            />
            {errors.password && <span className="field-error">{errors.password}</span>}
          </div>

          <div className="field-group">
            <label className="field-label">이름</label>
            <input
              className={`field-input ${errors.name ? 'error' : ''}`}
              type="text"
              name="name"
              placeholder="실명 입력"
              value={form.name}
              onChange={handleChange}
            />
            {errors.name && <span className="field-error">{errors.name}</span>}
          </div>

          <div className="field-group">
            <label className="field-label">이메일</label>
            <input
              className={`field-input ${errors.email ? 'error' : ''}`}
              type="email"
              name="email"
              placeholder="example@email.com"
              value={form.email}
              onChange={handleChange}
              autoComplete="email"
            />
            {errors.email && <span className="field-error">{errors.email}</span>}
          </div>

          <button type="submit" className="reg-btn">가입하기</button>
        </form>

        <p className="reg-login-link">
          이미 계정이 있으신가요?{' '}
          <span onClick={() => navigate(-1)} className="link-text">뒤로 가기</span>
        </p>
      </div>
    </div>
  );
}
