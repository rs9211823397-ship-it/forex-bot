import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import * as SecureStore from "expo-secure-store";
import { api, setAuthToken } from "../api/client";

interface AuthUser { id: number; username: string; role: string }

interface AuthCtx {
  token: string | null;
  user: AuthUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>({
  token: null, user: null, loading: true,
  login: async () => ({ ok: false }),
  logout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // Restore session token on app start
  useEffect(() => {
    (async () => {
      try {
        const saved = await SecureStore.getItemAsync("aaqts_token");
        if (saved) {
          setAuthToken(saved);
          const me = await api.me();
          setToken(saved);
          setUser(me.user);
        }
      } catch {
        await SecureStore.deleteItemAsync("aaqts_token").catch(() => {});
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    try {
      const r = await api.login(username, password);
      setAuthToken(r.token);
      await SecureStore.setItemAsync("aaqts_token", r.token);
      setToken(r.token);
      setUser(r.user);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : "Login failed" };
    }
  }, []);

  const logout = useCallback(async () => {
    try { await api.logout(); } catch {}
    setAuthToken(null);
    await SecureStore.deleteItemAsync("aaqts_token").catch(() => {});
    setToken(null);
    setUser(null);
  }, []);

  return <Ctx.Provider value={{ token, user, loading, login, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
