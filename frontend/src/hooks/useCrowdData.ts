/**
 * hooks/useCrowdData.ts — React hook for real-time crowd density polling.
 *
 * Polls the crowd snapshot endpoint every POLL_INTERVAL_MS milliseconds.
 * Uses a ref for the interval ID to avoid stale closure issues.
 *
 * Accessibility consideration: The component consuming this hook must wrap
 * updates in an aria-live region so screen readers announce changes
 * (see AlertBanner and ZoneIndicator components).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchCrowdSnapshot } from "../services/apiClient";
import type { ApiError, StadiumCrowdSnapshot } from "../types/api";

/** Poll every 30 seconds — balances freshness with server load */
const POLL_INTERVAL_MS = 30_000;

interface UseCrowdDataResult {
  snapshot: StadiumCrowdSnapshot | null;
  isLoading: boolean;
  error: ApiError | null;
  /** Trigger an immediate refresh outside the polling cycle */
  refresh: () => void;
}

export function useCrowdData(stadiumId: string | null): UseCrowdDataResult {
  const [snapshot, setSnapshot] = useState<StadiumCrowdSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async (): Promise<void> => {
    if (!stadiumId) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchCrowdSnapshot(stadiumId);
      setSnapshot(data);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setIsLoading(false);
    }
  }, [stadiumId]);

  useEffect(() => {
    // Fetch immediately on mount or stadiumId change
    void fetchData();

    // Schedule periodic polling
    intervalRef.current = setInterval(() => {
      void fetchData();
    }, POLL_INTERVAL_MS);

    // Cleanup: clear interval on unmount or when stadiumId changes
    // Prevents stale updates arriving after component unmounts (memory leak)
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [fetchData]);

  return { snapshot, isLoading, error, refresh: fetchData };
}
