import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, get, post, setCsrfToken, setUnauthorizedHandler } from '@/api/client';
import type { SessionInfo, User } from '@/api/types';
import { setLanguage } from '@/i18n';

interface AuthState {
  loading: boolean;
  session: SessionInfo | null;
  user: User | null;
  can: (perm: string) => boolean;
  login: (username: string, password: string) => Promise<SessionInfo>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setSession: (s: SessionInfo | null) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  const setSession = useCallback((s: SessionInfo | null) => {
    setSessionState(s);
    setCsrfToken(s?.csrfToken ?? null);
    if (s?.user.language) setLanguage(s.user.language);
  }, []);

  const refresh = useCallback(async () => {
    try {
      setSession(await get<SessionInfo>('/auth/me'));
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setSession(null);
      else throw e;
    } finally {
      setLoading(false);
    }
  }, [setSession]);

  useEffect(() => {
    refresh().catch(() => setLoading(false));
    setUnauthorizedHandler(() => {
      setSession(null);
      // Keep the public system info; drop everything that belonged to the expired session.
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== '/system/info' });
    });
    return () => setUnauthorizedHandler(null);
  }, [refresh, setSession, qc]);

  const login = useCallback(
    async (username: string, password: string) => {
      const s = await post<SessionInfo>('/auth/login', { username, password });
      setSession(s);
      return s;
    },
    [setSession],
  );

  const logout = useCallback(async () => {
    try {
      await post('/auth/logout');
    } finally {
      setSession(null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== '/system/info' });
    }
  }, [setSession, qc]);

  const value = useMemo<AuthState>(
    () => ({
      loading,
      session,
      user: session?.user ?? null,
      can: (perm: string) => !!session?.permissions.includes(perm),
      login,
      logout,
      refresh,
      setSession,
    }),
    [loading, session, login, logout, refresh, setSession],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth outside AuthProvider');
  return ctx;
}
