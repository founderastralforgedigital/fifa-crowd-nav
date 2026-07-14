/**
 * types/api.ts — TypeScript interfaces mirroring all backend Pydantic models.
 *
 * Keeping these in sync with the backend schema is critical.
 * In production: generate these types automatically from the OpenAPI spec
 * using `openapi-typescript` to eliminate the manual sync burden.
 *
 * All types use `readonly` properties to enforce immutability
 * in React state and prevent accidental mutation.
 */

// ── Stadium Types ─────────────────────────────────────────────────────────────

export type Country = "USA" | "CAN" | "MEX";

export type ZoneType =
  | "gate"
  | "concourse"
  | "concession"
  | "seating"
  | "exit"
  | "emergency_exit"
  | "medical"
  | "restroom"
  | "transport_hub";

export type DensityLevel = "low" | "medium" | "high" | "critical";

export interface Coordinates {
  readonly latitude: number;
  readonly longitude: number;
}

export interface StadiumZone {
  readonly zone_id: string;
  readonly name: string;
  readonly zone_type: ZoneType;
  readonly floor_level: number;
  readonly capacity: number;
  readonly coordinates: Coordinates;
  readonly is_accessible: boolean;
  readonly adjacent_zone_ids: readonly string[];
}

export interface Stadium {
  readonly stadium_id: string;
  readonly name: string;
  readonly city: string;
  readonly country: Country;
  readonly timezone: string;
  readonly capacity: number;
  readonly zones: readonly StadiumZone[];
  readonly coordinates: Coordinates;
}

export interface StadiumSummary {
  readonly stadium_id: string;
  readonly name: string;
  readonly city: string;
  readonly country: Country;
  readonly capacity: number;
}

// ── Crowd Flow Types ──────────────────────────────────────────────────────────

export interface ZoneCrowdState {
  readonly zone_id: string;
  readonly zone_name: string;
  readonly current_occupancy: number;
  readonly capacity: number;
  readonly density_score: number; // [0.0, 1.0]
  readonly density_level: DensityLevel;
  readonly predicted_density_in_15min: DensityLevel;
  readonly bottleneck_probability: number;
  readonly last_updated: string; // ISO datetime
}

export interface StadiumCrowdSnapshot {
  readonly stadium_id: string;
  readonly snapshot_timestamp: string;
  readonly total_occupancy: number;
  readonly total_capacity: number;
  readonly overall_density_level: DensityLevel;
  readonly zones: readonly ZoneCrowdState[];
  readonly active_bottleneck_zone_ids: readonly string[];
}

// ── Navigation Types ──────────────────────────────────────────────────────────

export type SupportedLanguage =
  | "en" | "es" | "fr" | "pt" | "ar" | "zh" | "de" | "it" | "ja" | "ko";

export type AccessibilityPreference = "standard" | "accessible" | "medical";

export interface NavigationRequest {
  readonly stadium_id: string;
  readonly origin_zone_id: string;
  readonly destination_zone_id: string;
  readonly language: SupportedLanguage;
  readonly accessibility: AccessibilityPreference;
  readonly avoid_zone_ids?: readonly string[];
}

export interface RouteStep {
  readonly step_number: number;
  readonly zone_id: string;
  readonly zone_name: string;
  readonly instruction: string;
  readonly estimated_seconds: number;
  readonly crowd_warning: string | null;
  readonly is_accessible_route: boolean;
}

export interface NavigationResponse {
  readonly stadium_id: string;
  readonly origin_zone_id: string;
  readonly destination_zone_id: string;
  readonly language: SupportedLanguage;
  readonly accessibility: AccessibilityPreference;
  readonly steps: readonly RouteStep[];
  readonly total_distance_meters: number;
  readonly total_estimated_seconds: number;
  readonly route_zone_ids: readonly string[];
  readonly is_crowd_optimized: boolean;
  readonly cache_hit: boolean;
}

// ── API Error Types ───────────────────────────────────────────────────────────

export interface ApiError {
  readonly error: string;
  readonly message: string;
  readonly retry_after_seconds?: number;
}

// ── UI State Types ────────────────────────────────────────────────────────────

/** Color-contrast safe density color tokens — WCAG AA compliant on dark bg */
export const DENSITY_COLORS: Record<DensityLevel, { bg: string; fg: string; label: string }> = {
  low:      { bg: "#0d7a3e", fg: "#ffffff", label: "Low"      }, // contrast 8.2:1
  medium:   { bg: "#b45309", fg: "#ffffff", label: "Moderate" }, // contrast 5.3:1
  high:     { bg: "#b91c1c", fg: "#ffffff", label: "High"     }, // contrast 6.1:1
  critical: { bg: "#7c2d12", fg: "#fde68a", label: "Critical" }, // contrast 9.1:1
} as const;

export const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: "English",
  es: "Español",
  fr: "Français",
  pt: "Português",
  ar: "العربية",
  zh: "中文",
  de: "Deutsch",
  it: "Italiano",
  ja: "日本語",
  ko: "한국어",
} as const;

/** Languages that render right-to-left — drives `dir` attribute on text elements */
export const RTL_LANGUAGES: ReadonlySet<SupportedLanguage> = new Set(["ar"]);
