"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type Query } from "./api-client";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  /** Replace the data locally (after a change whose result is already known). */
  setData: (value: T | null) => void;
}

/**
 * Loads `path` (relative to the API root, e.g. "companies/<id>/accounts") and reloads when the path or
 * query changes. Pass null to skip loading (for example while no company is chosen yet). The previous data
 * stays on screen while a reload is in flight, so tables do not flash empty.
 */
export function useApi<T>(path: string | null, query?: Query): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [tick, setTick] = useState(0);
  const queryKey = JSON.stringify(query ?? {});
  const latest = useRef(0);

  useEffect(() => {
    if (path === null) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const mine = ++latest.current;
    setLoading(true);
    setError(null);
    api<T>(path, { query: JSON.parse(queryKey) as Query, signal: controller.signal })
      .then((result) => {
        if (latest.current === mine) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err) => {
        if ((err as { name?: string }).name === "AbortError") return;
        if (latest.current === mine) {
          setError(errorMessage(err));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [path, queryKey, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload, setData };
}