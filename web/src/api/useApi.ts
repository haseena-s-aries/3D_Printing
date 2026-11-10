import { useCallback, useEffect, useRef, useState } from "react";

import { useSessionKey } from "../auth/AuthContext";
import { api, type RequestOptions } from "./client";

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

  if (lastSession.current !== sessionKey) {
    lastSession.current = sessionKey;
    latest.current += 1; // invalidate anything still in flight for the previous organisation
  }

  const load = useCallback(async () => {
    if (!path) return;
    const id = ++latest.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api<T>(path, opts);
      if (id === latest.current) setData(result);
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
  }, [sessionKey]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}
