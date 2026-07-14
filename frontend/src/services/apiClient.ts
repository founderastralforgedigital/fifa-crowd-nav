/**
 * services/apiClient.ts — Typed Axios HTTP client for the FIFA 2026 Navigation API.
 *
 * Design decisions:
 * 1. Single Axios instance — consistent base URL, headers, and interceptors.
 * 2. JWT token injected via request interceptor — never hardcoded in call sites.
 * 3. Error interceptor normalizes backend errors into typed ApiError objects.
 * 4. All functions are fully typed — no `any` types anywhere.
 *
 * Token storage: In a production app, use HttpOnly cookies (not localStorage)
 * to prevent XSS token theft. This implementation uses sessionStorage as
 * a reasonable dev-mode compromise with a clear comment about the tradeoff.
 */

import axios, { AxiosError, AxiosInstance, AxiosResponse } from "axios";
import type {
  ApiError,
  NavigationRequest,
  NavigationResponse,
  Stadium,
  StadiumCrowdSnapshot,
  StadiumSummary,
} from "../types/api";

// Read from Vite environment variables (set in .env.local or injected at build time)
const API_BASE_URL: string =
  (import.meta as { env: Record<string, string> }).env.VITE_API_BASE_URL ??
  "http://localhost:8000";

// ── Axios Instance ────────────────────────────────────────────────────────────

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15_000, // 15 seconds — accounts for GenAI API latency
  headers: {
    "Content-Type": "application/json",
    // Unique request ID for distributed tracing across frontend + backend logs
    "X-Request-ID": crypto.randomUUID(),
  },
});

// ── Request Interceptor: JWT Injection ────────────────────────────────────────

apiClient.interceptors.request.use((config) => {
  /**
   * Security note: sessionStorage is cleared when the browser tab closes,
   * limiting the exposure window vs localStorage (persists across sessions).
   * For production, migrate to HttpOnly SameSite=Strict cookies to prevent
   * XSS-based token theft entirely.
   */
  const token = sessionStorage.getItem("access_token");
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response Interceptor: Error Normalization ─────────────────────────────────

apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError<{ detail: ApiError }>) => {
    if (error.response?.data?.detail) {
      // Backend returned a structured error — re-throw as-is for typed handling
      return Promise.reject(error.response.data.detail as ApiError);
    }
    // Network error or unexpected format
    const fallbackError: ApiError = {
      error: "network_error",
      message: error.message || "Unable to connect to the navigation service.",
    };
    return Promise.reject(fallbackError);
  }
);

// ── Public Token Management ───────────────────────────────────────────────────

export function setAuthToken(token: string): void {
  sessionStorage.setItem("access_token", token);
}

export function clearAuthToken(): void {
  sessionStorage.removeItem("access_token");
}

// ── API Functions ─────────────────────────────────────────────────────────────

/**
 * Fetch all 16 FIFA 2026 host stadiums.
 * No authentication required — publicly accessible.
 */
export async function fetchStadiums(): Promise<StadiumSummary[]> {
  const response = await apiClient.get<StadiumSummary[]>("/api/v1/stadiums");
  return response.data;
}

/**
 * Fetch full stadium details including zone topology.
 */
export async function fetchStadium(stadiumId: string): Promise<Stadium> {
  const response = await apiClient.get<Stadium>(`/api/v1/stadiums/${stadiumId}`);
  return response.data;
}

/**
 * Fetch real-time crowd density snapshot for a stadium.
 * Requires authentication (fan, operator, or admin role).
 */
export async function fetchCrowdSnapshot(
  stadiumId: string
): Promise<StadiumCrowdSnapshot> {
  const response = await apiClient.get<StadiumCrowdSnapshot>(
    `/api/v1/crowd/${stadiumId}`
  );
  return response.data;
}

/**
 * Request a crowd-optimized, multilingual navigation route.
 * Requires authentication.
 *
 * @param request - NavigationRequest with origin, destination, language, accessibility
 * @returns NavigationResponse with step-by-step localized instructions
 */
export async function navigate(
  request: NavigationRequest
): Promise<NavigationResponse> {
  const response = await apiClient.post<NavigationResponse>(
    "/api/v1/navigate",
    request
  );
  return response.data;
}
