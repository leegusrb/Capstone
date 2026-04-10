import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoginModal from './LoginModal';
import './Navbar.css';

export default function Navbar() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [showLogin, setShowLogin] = useState(false);

  return (
    <>
      <nav className="navbar">
        <div className="navbar-inner">
          {/* Logo */}
          <div className="navbar-logo" onClick={() => navigate('/')}>
            <div className="logo-icon">
              <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
                <circle cx="13" cy="6" r="4" fill="#4f6ef7"/>
                <circle cx="6" cy="20" r="4" fill="#10b981"/>
                <circle cx="20" cy="20" r="4" fill="#8b5cf6"/>
                <line x1="13" y1="9.5" x2="7.5" y2="17" stroke="#c7d2fe" strokeWidth="1.8"/>
                <line x1="13" y1="9.5" x2="18.5" y2="17" stroke="#c7d2fe" strokeWidth="1.8"/>
                <line x1="9" y1="20" x2="17" y2="20" stroke="#c7d2fe" strokeWidth="1.8"/>
              </svg>
            </div>
            <span className="logo-text">KG-Tutor</span>
          </div>

          {/* Spacer */}
          <div style={{ flex: 1 }} />

          {/* Right side */}
          <div className="navbar-right">
            {user ? (
              <>
                <NavLink to="/archive" className={({ isActive }) => `nav-link archive-link ${isActive ? 'active' : ''}`}>
                  <span>🗂️</span>
                  <span>나의 저장소</span>
                </NavLink>

                <div className="profile-wrap">
                  <button className="profile-btn" title={`${user.name}님`}>
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="8" r="4" stroke="#4f6ef7" strokeWidth="2"/>
                      <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" stroke="#4f6ef7" strokeWidth="2" strokeLinecap="round"/>
                    </svg>
                  </button>
                  <div className="profile-dropdown">
                    <div className="dropdown-name">{user.name}님</div>
                    <div className="dropdown-id">@{user.id}</div>
                    <hr className="dropdown-divider"/>
                    <button className="dropdown-logout" onClick={logout}>로그아웃</button>
                  </div>
                </div>
              </>
            ) : (
              <button className="login-btn" onClick={() => setShowLogin(true)}>
                로그인
              </button>
            )}
          </div>
        </div>
      </nav>

      {showLogin && <LoginModal onClose={() => setShowLogin(false)} />}
    </>
  );
}
