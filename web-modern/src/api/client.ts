/**
 * API client for /api/v1.
 * - Access token kept in memory only; refresh token in sessionStorage (cleared when the tab closes).
 *   Moving the refresh token to an httpOnly cookie is a Phase 2 hardening item.
 * - On 401 the client refreshes once and retries; if refresh fails the session ends.
 * - Every error is surfaced as ApiError with the server's stable code and message.
 */
import type { ApiErrorBody, Session, TokenResponse } from "@passport/api-types";

import { track } from "./activity";

const BASE = "/api/v1";
const REFRESH_KEY = "passport.refresh";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}, public requestId = "") {
    super(message);
  }
}

let accessToken: string | null = null;
let onSessionEnded: (() => void) | null = null;

export function setSessionEndedHandler(fn: () => void) {
  onSessionEnded = fn;
}

export function setTokens(access: string | null, refresh?: string | null) {
  accessToken = access;
  try {
    if (refresh === null) sessionStorage.removeItem(REFRESH_KEY);
    else if (refresh) sessionStorage.setItem(REFRESH_KEY, refresh);
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
}

export function storedRefreshToken(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

async function toError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> = {};
  try {
    body = await res.json();
  } catch {
    /* non-JSON error */
  }
  const e = body.error;
  return new ApiError(res.status, e?.code ?? `http_${res.status}`, e?.message ?? res.statusText ?? "Request failed", e?.details ?? {}, e?.request_id ?? "");
}

let refreshing: Promise<boolean> | null = null;

export async function refreshAccess(): Promise<boolean> {
  const refresh = storedRefreshToken();
  if (!refresh) return false;
  refreshing ??= (async () => {
    const res = await fetch(`${BASE}/auth/refresh/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh }) });
    if (!res.ok) {
      setTokens(null, null);
      return false;
    }
    const data = (await res.json()) as { access: string; refresh: string };
    setTokens(data.access, data.refresh);
    return true;
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  form?: FormData;
}

export async function api<T>(path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  // saves show the top progress bar (reads are tracked by useApi on a page's first load only)
  if (!retried && (opts.method && opts.method !== "GET" || opts.body !== undefined || opts.form)) return track(request<T>(path, opts, retried));
  return request<T>(path, opts, retried);
}

async function request<T>(path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(url.pathname + url.search, { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  if (res.status === 401 && !retried && path !== "/auth/token/" && (await refreshAccess())) {
    return api<T>(path, opts, true);
  }
  if (res.status === 401 && path !== "/auth/token/") onSessionEnded?.();
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Authenticated binary fetch (thumbnails): returns an object URL the caller must revoke. */
export async function fetchObjectUrl(path: string, retried = false): Promise<string> {
  if (!retried) return track(fetchObjectUrlInner(path));
  return fetchObjectUrlInner(path, true);
}

async function fetchObjectUrlInner(path: string, retried = false): Promise<string> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(`${BASE}${path}`, { headers });
  if (res.status === 401 && !retried && (await refreshAccess())) return fetchObjectUrl(path, true);
  if (!res.ok) throw await toError(res);
  return URL.createObjectURL(await res.blob());
}

/** POST a JSON body and receive a file (e.g. an assembled report preview) as an object URL. */
export async function postForObjectUrl(path: string, body: unknown, retried = false): Promise<string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(`${BASE}${path}`, { method: "POST", headers, body: JSON.stringify(body) });
  if (res.status === 401 && !retried && (await refreshAccess())) return postForObjectUrl(path, body, true);
  if (!res.ok) throw await toError(res);
  return URL.createObjectURL(await res.blob());
}

/** Multipart upload with progress (fetch has no upload progress events). */
export function upload<T>(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const send = (retried: boolean) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}${path}`);
      if (accessToken) xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
      xhr.setRequestHeader("Accept", "application/json");
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onerror = () => reject(new ApiError(0, "network_error", "The upload failed because of a network problem."));
      xhr.onload = async () => {
        if (xhr.status === 401 && !retried && (await refreshAccess())) return send(true);
        let data: unknown = null;
        try {
          data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
        else {
          const e = (data as ApiErrorBody | null)?.error;
          reject(new ApiError(xhr.status, e?.code ?? `http_${xhr.status}`, e?.message ?? "Upload failed.", e?.details ?? {}, e?.request_id ?? ""));
        }
      };
      xhr.send(form);
    };
    send(false);
  });
}

export async function login(email: string, password: string, tenant?: string): Promise<Session> {
  const data = await api<TokenResponse>("/auth/token/", { body: { email, password, ...(tenant ? { tenant } : {}) } });
  setTokens(data.access, data.refresh);
  return data.session;
}

/** Move the session to another organisation the user already belongs to; the old refresh token is revoked. */
export async function switchTenant(tenant: string): Promise<Session> {
  const data = await api<TokenResponse>("/auth/switch/", { body: { tenant, refresh: storedRefreshToken() } });
  setTokens(data.access, data.refresh);
  return data.session;
}

export async function logout() {
  const refresh = storedRefreshToken();
  try {
    if (refresh && accessToken) await api("/auth/logout/", { body: { refresh } });
  } finally {
    setTokens(null, null);
  }
}

export async function resumeSession(): Promise<Session | null> {
  if (!(await refreshAccess())) return null;
  try {
    return await api<Session>("/auth/me/");
  } catch {
    return null;
  }
}
