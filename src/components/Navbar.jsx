import { NavLink, useNavigate } from 'react-router-dom';
import './Navbar.css';

const NAV_LINKS = [
  { to: '/upload',   label: '파일 업로드',  icon: '📄' },
  { to: '/student',  label: '학생 모드',    icon: '🎓' },
  { to: '/teacher',  label: '선생님 모드',  icon: '🧑‍🏫' },
  { to: '/report',   label: '리포트',       icon: '📊' },
];

export default function Navbar() {
  const navigate = useNavigate();

  return (
    <nav className="navbar">
      <div className="navbar-inner">
        {/* Logo → Main */}
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

        {/* Center nav links */}
        <div className="navbar-links">
          {NAV_LINKS.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>

        {/* Archive — pushed to right */}
        <NavLink to="/archive" className={({ isActive }) => `nav-link archive-link ${isActive ? 'active' : ''}`}>
          <span>🗂️</span>
          <span>나의 저장소</span>
        </NavLink>
      </div>
    </nav>
  );
}
