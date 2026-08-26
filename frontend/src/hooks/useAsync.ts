import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../lib/api";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
}

/**
 * Fetch-on-mount with a mounted guard.
 *
 * The guard is not ceremony: several screens here fire a request that takes a
 * second or two, and navigating away mid-flight would otherwise set state on an
 * unmounted component and, worse, let a stale response overwrite a newer one.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [nonce, setNonce] = useState(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    fn()
      .then((value) => {
        if (current && alive.current) setData(value);
      })
      .catch((err) => {
        if (current && alive.current) {
          setError(
            err instanceof ApiError
              ? err
              : new ApiError(0, "network", "Could not reach the API."),
          );
        }
      })
      .finally(() => {
        if (current && alive.current) setLoading(false);
      });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}
