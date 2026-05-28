import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../api/client';
import {
  clearStoredAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
} from './tokenStorage';
import { AuthContext } from './authState';
import type { AuthContextValue } from './authState';
import type { LoginResponse, UserProfile } from './authTypes';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredAuthToken());
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const persistToken = useCallback((nextToken: string | null) => {
    if (nextToken) {
      setStoredAuthToken(nextToken);
    } else {
      clearStoredAuthToken();
    }
    setToken(nextToken);
  }, []);

  const logout = useCallback(() => {
    persistToken(null);
    setUser(null);
  }, [persistToken]);

  const refreshMe = useCallback(async () => {
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }

    try {
      const response = await api.get<UserProfile>('/auth/me');
      setUser(response.data);
    } catch {
      logout();
    } finally {
      setIsLoading(false);
    }
  }, [logout, token]);

  useEffect(() => {
    void refreshMe();
  }, [refreshMe]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await api.post<LoginResponse>('/auth/login', { username, password });
    persistToken(response.data.access_token);
    setUser(response.data.user);
  }, [persistToken]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      isLoading,
      login,
      logout,
      refreshMe,
    }),
    [isLoading, login, logout, refreshMe, token, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
