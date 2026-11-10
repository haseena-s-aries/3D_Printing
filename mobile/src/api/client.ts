/**
 * Mobile API client for /api/v1 (same contract as the web portal; types shared from @passport/api-types).
 * - Bound to one deployment and, after sign-in, one tenant (MOB-006). A session whose tenant differs from
 *   the bound tenant is rejected and cleared.
 * - Refreshes the access token once on 401; on failure the session ends.
 */
import type {ApiErrorBody, Session, TokenResponse} from '@passport/api-types';

import type {Deployment} from '../config/deployments';
import type {TokenStore} from './tokenStore';

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
    public requestId = '',
  ) {
    super(message);
  }
}

type FetchLike = (input: string, init?: {method?: string; headers?: Record<string, string>; body?: string}) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

export class ApiClient {
  private access: string | null = null;
  private boundTenantId: string | null = null;
  private refreshing: Promise<boolean> | null = null;
  onSessionEnded: (() => void) | null = null;

  constructor(readonly deployment: Deployment, private store: TokenStore, private fetchImpl: FetchLike = fetch as unknown as FetchLike) {}

  private url(path: string, query?: Record<string, string | number | undefined>) {
    const q = Object.entries(query ?? {})
      .filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&');
    return `${this.deployment.apiBaseUrl}/api/v1${path}${q ? `?${q}` : ''}`;
  }

  private async toError(res: {status: number; json(): Promise<unknown>}): Promise<ApiError> {
    let body: Partial<ApiErrorBody> = {};
    try {
      body = ((await res.json()) ?? {}) as Partial<ApiErrorBody>;
    } catch {
      /* not JSON */
    }
    const e = body.error;
    return new ApiError(res.status, e?.code ?? `http_${res.status}`, e?.message ?? 'Request failed.', e?.details ?? {}, e?.request_id ?? '');
  }

  async login(email: string, password: string, tenant?: string): Promise<Session> {
    const res = await this.fetchImpl(this.url('/auth/token/'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json', Accept: 'application/json'},
      body: JSON.stringify({email, password, ...(tenant ? {tenant} : {})}),
    });
    if (!res.ok) {
      throw await this.toError(res);
    }
    const data = (await res.json()) as TokenResponse;
    this.access = data.access;
    this.boundTenantId = data.session.tenant.id;
    await this.store.saveRefresh(this.deployment.id, data.refresh);
    return data.session;
  }

  async refresh(): Promise<boolean> {
    this.refreshing ??= (async () => {
      const token = await this.store.loadRefresh(this.deployment.id);
      if (!token) {
        return false;
      }
      const res = await this.fetchImpl(this.url('/auth/refresh/'), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({refresh: token}),
      });
      if (!res.ok) {
        await this.endSession();
        return false;
      }
      const data = (await res.json()) as {access: string; refresh: string};
      this.access = data.access;
      await this.store.saveRefresh(this.deployment.id, data.refresh);
      return true;
    })().finally(() => {
      this.refreshing = null;
    });
    return this.refreshing;
  }

  async request<T>(path: string, opts: {method?: string; body?: unknown; query?: Record<string, string | number | undefined>} = {}, retried = false): Promise<T> {
    const headers: Record<string, string> = {Accept: 'application/json'};
    if (this.access) {
      headers.Authorization = `Bearer ${this.access}`;
    }
    let body: string | undefined;
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.body);
    }
    const res = await this.fetchImpl(this.url(path, opts.query), {method: opts.method ?? (body ? 'POST' : 'GET'), headers, body});
    if (res.status === 401 && !retried && (await this.refresh())) {
      return this.request<T>(path, opts, true);
    }
    if (res.status === 401) {
      await this.endSession();
    }
    if (!res.ok) {
      throw await this.toError(res);
    }
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  /** Restore a session from the stored refresh token and check the tenant binding. */
  async resume(): Promise<Session | null> {
    if (!(await this.refresh())) {
      return null;
    }
    const session = await this.request<Session>('/auth/me/');
    return this.bind(session);
  }

  bind(session: Session): Session {
    if (this.boundTenantId && this.boundTenantId !== session.tenant.id) {
      void this.endSession();
      throw new ApiError(401, 'tenant_binding_mismatch', 'The session does not belong to the selected organisation.');
    }
    this.boundTenantId = session.tenant.id;
    return session;
  }

  async logout(): Promise<void> {
    const token = await this.store.loadRefresh(this.deployment.id);
    try {
      if (token && this.access) {
        await this.request('/auth/logout/', {body: {refresh: token}});
      }
    } finally {
      await this.endSession();
    }
  }

  async endSession(): Promise<void> {
    this.access = null;
    this.boundTenantId = null;
    await this.store.clear(this.deployment.id);
    this.onSessionEnded?.();
  }
}
