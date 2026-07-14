/**
 * hooks/useNavigation.ts — React hook for navigation route requests.
 *
 * Manages loading, error, and result state for a navigation request.
 * Exposes a typed `requestRoute` function that components call on user interaction.
 */

import { useCallback, useState } from "react";
import { navigate } from "../services/apiClient";
import type { ApiError, NavigationRequest, NavigationResponse } from "../types/api";

interface UseNavigationResult {
  route: NavigationResponse | null;
  isLoading: boolean;
  error: ApiError | null;
  requestRoute: (request: NavigationRequest) => Promise<void>;
  clearRoute: () => void;
}

export function useNavigation(): UseNavigationResult {
  const [route, setRoute] = useState<NavigationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const requestRoute = useCallback(async (request: NavigationRequest): Promise<void> => {
    setIsLoading(true);
    setError(null);
    setRoute(null);
    try {
      const result = await navigate(request);
      setRoute(result);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const clearRoute = useCallback(() => {
    setRoute(null);
    setError(null);
  }, []);

  return { route, isLoading, error, requestRoute, clearRoute };
}
