import { createContext, useContext, useState } from 'react';

const AuthContext = createContext(null);

const API_BASE = 'http://localhost:8000/api/v1';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('kg_user')) || null; }
    catch { return null; }
  });

  async function register({ id, password, name, email }) {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: id, password, name, email }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { ok: false, msg: data.detail || '회원가입에 실패했습니다.' };
    }
    return { ok: true };
  }

  async function login({ id, password }) {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: id, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { ok: false, msg: data.detail || '로그인에 실패했습니다.' };
    }
    setUser(data);
    localStorage.setItem('kg_user', JSON.stringify(data));
    return { ok: true };
  }

  function logout() {
    setUser(null);
    localStorage.removeItem('kg_user');
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, register }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
