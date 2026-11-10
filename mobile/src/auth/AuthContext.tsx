import type {Session} from '@passport/api-types';
import React, {createContext, useCallback, useContext, useEffect, useMemo, useState} from 'react';

import {ApiClient} from '../api/client';

interface AuthState {
  client: ApiClient;
  session: Session | null;
  ready: boolean;
  login: (email: string, password: string, tenant?: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (capability: string) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({client, children}: {client: ApiClient; children: React.ReactNode}) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    client.onSessionEnded = () => setSession(null);
    client
      .resume()
      .then(setSession)
      .catch(() => setSession(null))
      .finally(() => setReady(true));
  }, [client]);

  const login = useCallback(
    async (email: string, password: string, tenant?: string) => {
      setSession(await client.login(email, password, tenant));
    },
    [client],
  );
  const logout = useCallback(async () => {
    await client.logout();
    setSession(null);
  }, [client]);

  const value = useMemo<AuthState>(
    () => ({client, session, ready, login, logout, can: c => !!session?.capabilities.includes(c)}),
    [client, session, ready, login, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) {
    throw new Error('useAuth outside AuthProvider');
  }
  return v;
}
