import { createContext, useContext, useState } from 'react';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('kg_user')) || null; }
    catch { return null; }
  });

  function register({ id, password, name, email }) {
    const users = getUsers();
    if (users.find(u => u.id === id)) return { ok: false, msg: '이미 사용 중인 아이디입니다.' };
    const newUser = { id, password, name, email };
    localStorage.setItem('kg_users', JSON.stringify([...users, newUser]));
    return { ok: true };
  }

  function login({ id, password }) {
    const users = getUsers();
    const found = users.find(u => u.id === id && u.password === password);
    if (!found) return { ok: false, msg: '아이디 또는 비밀번호가 올바르지 않습니다.' };
    const { password: _, ...safe } = found;
    setUser(safe);
    localStorage.setItem('kg_user', JSON.stringify(safe));
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

function getUsers() {
  try { return JSON.parse(localStorage.getItem('kg_users')) || []; }
  catch { return []; }
}

export function useAuth() {
  return useContext(AuthContext);
}
