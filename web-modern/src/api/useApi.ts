import { useCallback, useEffect, useRef, useState } from "react";

import { useSessionKey } from "../auth/AuthContext";
import { track } from "./activity";
import { api, type RequestOptions } from "./client";

// Identical GETs started while one is still in flight share it (two components mounting with the same query, or
// React's development double-mount): one network request instead of two. Explicit reloads always fetch again.
const inFlight = new Map<string, Promise<unknown>>();
function shared<T>(key: string, run: () => Promise<T>): Promise<T> {
  const hit = inFlight.get(key) as Promise<T> | undefined;
  if (hit) return hit;
  const p = run().finally(() => inFlight.delete(key));
  inFlight.set(key, p);
  return p;
}

export function useApi<T>(path: string | null, opts?: RequestOptions) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(!!path);
  // The selected organisation is part of the request identity: switching organisation reloads every organisation-
  // specific request, and the previous organisation's data is cleared instead of being shown under the new name.
  const sessionKey = useSessionKey();
  const key = `${sessionKey}|${path}${JSON.stringify(opts?.query ?? {})}`;
  // Only the latest request may update state: a slow response for an earlier filter, sort or organisation must not
  // overwrite the result of a newer one.
  const latest = useRef(0);
  const lastSession = useRef(sessionKey);
  // the first load of a page's data (or of a new filter / search) shows the top progress bar; background reloads do not
  const hasData = useRef(false);
  const loadedKey = useRef("");

  if (lastSession.current !== sessionKey) {
    lastSession.current = sessionKey;
    latest.current += 1; // invalidate anything still in flight for the previous organisation
  }

  const load = useCallback(async (reuse = false) => {
    if (!path) return;
    const id = ++latest.current;
    setLoading(true);
    setError(null);
    try {
      const run = reuse && !opts?.body && !opts?.method ? shared(key, () => api<T>(path, opts)) : api<T>(path, opts);
      const result = await (hasData.current && loadedKey.current === key ? run : track(run));
      if (id === latest.current) { hasData.current = true; loadedKey.current = key; setData(result); }
    } catch (e) {
      if (id === latest.current) setError(e);
    } finally {
      if (id === latest.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    setData(null); // organisation changed: never show the previous organisation's data while the new one loads
    setError(null);
    hasData.current = false;
  }, [sessionKey]);

  useEffect(() => {
    void load(true);
  }, [load]);

  const reload = useCallback(() => load(false), [load]);
  return { data, error, loading, reload, setData };
}
