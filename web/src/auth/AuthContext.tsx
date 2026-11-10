import type { Session } from "@passport/api-types";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import * as client from "../api/client";

interface AuthState {
  session: Session | null;
  ready: boolean;
  /** User of the most recent session; lets the login page return only that same user to where they were. */
  lastUserId: string | null;
  login: (email: string, password: string, tenant?: string) => Promise<Session>;
  switchTenant: (slug: string) => Promise<Session>;
  logout: () => Promise<void>;
  can: (capability: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children, initial = null }: { children: ReactNode; initial?: Session | null }) {
  const [session, setSession] = useState<Session | null>(initial);
  const [ready, setReady] = useState(initial !== null);
  const lastUser = useRef<string | null>(initial?.user.id ?? null);
  if (session) lastUser.current = session.user.id;

  useEffect(() => {
    client.setSessionEndedHandler(() => setSession(null));
    if (initial) return;
    let cancelled = false;
    client.resumeSession().then((s) => {
      if (!cancelled) {
        setSession(s);
        setReady(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [initial]);

  const login = useCallback(async (email: string, password: string, tenant?: string) => {
    const s = await client.login(email, password, tenant);
    setSession(s);
    return s;
  }, []);

  const switchTenant = useCallback(async (slug: string) => {
    const s = await client.switchTenant(slug);
    setSession(s);
    return s;
  }, []);

  const logout = useCallback(async () => {
    await client.logout();
    setSession(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ session, ready, lastUserId: lastUser.current, login, switchTenant, logout, can: (c: string) => !!session?.capabilities.includes(c) }),
    [session, ready, login, switchTenant, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Identity of the selected organisation (membership); empty outside a signed-in session. Data hooks include it in
 *  their request identity so that switching organisation reloads everything and drops older responses. */
export function useSessionKey(): string {
  return useContext(AuthContext)?.session?.membership.id ?? "";
}

/**
 * Where to go after sign-in (review defect D-4): the remembered page, unless it was left by a different user
 * (sign-out, then someone else signs in). Deep links opened with no prior session are kept.
 */
export function postLoginTarget(state: unknown, userId: string): string {
  const s = state as { from?: string; user?: string | null } | null;
  return s?.from && (s.user == null || s.user === userId) ? s.from : "/";
}
