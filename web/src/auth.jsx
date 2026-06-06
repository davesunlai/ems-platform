import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { applyTheme } from "./theme";
import { api, getToken, setToken, clearToken, setUnauthorizedHandler } from "./api";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => { clearToken(); setUser(null); }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    if (!getToken()) { setLoading(false); return; }
    api.me().then((u) => { setUser(u); if (u) applyTheme(u.theme, u.theme_custom); }).catch(() => clearToken()).finally(() => setLoading(false));
  }, []);

  const login = async (username, password) => {
    const res = await api.login(username, password);
    setToken(res.access_token);
    setUser({ username, role: res.role, permissions: res.permissions });
  };

  const has = (perm) => !!user && user.permissions.includes(perm);

  return (
    <AuthCtx.Provider value={{ user, loading, login, logout, has }}>
      {children}
    </AuthCtx.Provider>
  );
}
