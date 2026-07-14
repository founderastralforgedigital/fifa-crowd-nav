/**
 * components/NavigationPanel/NavigationPanel.tsx — Full navigation UI panel.
 *
 * WCAG 2.1 AA compliance:
 * - Form controls have explicit <label> associations (htmlFor).
 * - aria-busy="true" set on the submit button during loading.
 * - aria-describedby connects the form to its error message.
 * - Route results rendered as <ol> (ordered list — steps are sequential).
 * - aria-live="polite" on results region announces route completion to AT.
 * - Loading state communicated via both visual spinner and aria-label.
 * - Focus moves to the first route step on successful route computation.
 */

import React, { useEffect, useRef, useState } from "react";
import { useNavigation } from "../../hooks/useNavigation";
import type { AccessibilityPreference, StadiumZone, SupportedLanguage } from "../../types/api";
import { RTL_LANGUAGES } from "../../types/api";
import { AlertBanner } from "../AlertBanner/AlertBanner";
import { RouteStep } from "./RouteStep";

interface NavigationPanelProps {
  readonly stadiumId: string;
  readonly zones: readonly StadiumZone[];
  readonly language: SupportedLanguage;
}

export const NavigationPanel: React.FC<NavigationPanelProps> = ({
  stadiumId,
  zones,
  language,
}) => {
  const { route, isLoading, error, requestRoute, clearRoute } = useNavigation();
  const [origin, setOrigin] = useState<string>("");
  const [destination, setDestination] = useState<string>("");
  const [accessibility, setAccessibility] = useState<AccessibilityPreference>("standard");
  const [formError, setFormError] = useState<string>("");

  const isRtl = RTL_LANGUAGES.has(language);
  const errorId = "nav-form-error";
  const resultsRef = useRef<HTMLOListElement>(null);

  // Move focus to the first route step when results arrive — WCAG SC 2.4.3
  useEffect(() => {
    if (route && resultsRef.current) {
      const firstStep = resultsRef.current.querySelector("li");
      if (firstStep instanceof HTMLElement) {
        firstStep.focus({ preventScroll: false });
        firstStep.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }, [route]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");

    // Client-side validation before API call
    if (!origin) {
      setFormError("Please select your current location.");
      return;
    }
    if (!destination) {
      setFormError("Please select your destination.");
      return;
    }
    if (origin === destination) {
      setFormError("Origin and destination must be different zones.");
      return;
    }

    await requestRoute({
      stadium_id: stadiumId,
      origin_zone_id: origin,
      destination_zone_id: destination,
      language,
      accessibility,
    });
  };

  const fieldStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: "0.375rem",
  };

  const labelStyle: React.CSSProperties = {
    fontSize: "0.875rem",
    fontWeight: 600,
    color: "#94a3b8",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  };

  const selectStyle: React.CSSProperties = {
    backgroundColor: "#0f172a",
    color: "#f1f5f9",
    border: "1px solid #334155",
    borderRadius: "0.375rem",
    padding: "0.625rem 0.875rem",
    fontSize: "1rem",
    width: "100%",
  };

  return (
    <section
      aria-labelledby="nav-panel-heading"
      dir={isRtl ? "rtl" : "ltr"}
      style={{
        backgroundColor: "#1e293b",
        borderRadius: "0.75rem",
        padding: "1.5rem",
        display: "flex",
        flexDirection: "column",
        gap: "1.25rem",
      }}
    >
      <h2
        id="nav-panel-heading"
        style={{ margin: 0, fontSize: "1.25rem", color: "#f1f5f9" }}
      >
        🗺️ Get Directions
      </h2>

      {/* Navigation form */}
      <form
        onSubmit={handleSubmit}
        aria-describedby={formError ? errorId : undefined}
        noValidate
        style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
      >
        {/* Origin selector */}
        <div style={fieldStyle}>
          <label htmlFor="origin-select" style={labelStyle}>
            Current Location
          </label>
          <select
            id="origin-select"
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            required
            aria-required="true"
            style={selectStyle}
          >
            <option value="">— Select your zone —</option>
            {zones.map((z) => (
              <option key={z.zone_id} value={z.zone_id}>
                {z.name}
              </option>
            ))}
          </select>
        </div>

        {/* Destination selector */}
        <div style={fieldStyle}>
          <label htmlFor="dest-select" style={labelStyle}>
            Destination
          </label>
          <select
            id="dest-select"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            required
            aria-required="true"
            style={selectStyle}
          >
            <option value="">— Select destination —</option>
            {zones.map((z) => (
              <option key={z.zone_id} value={z.zone_id}>
                {z.name}
              </option>
            ))}
          </select>
        </div>

        {/* Accessibility preference */}
        <fieldset
          style={{
            border: "1px solid #334155",
            borderRadius: "0.375rem",
            padding: "0.75rem 1rem",
            margin: 0,
          }}
        >
          <legend
            style={{
              ...labelStyle,
              padding: "0 0.25rem",
              color: "#94a3b8",
            }}
          >
            Accessibility
          </legend>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            {(
              [
                { value: "standard",   label: "Standard",   desc: "Fastest route" },
                { value: "accessible", label: "♿ Accessible", desc: "Ramps & lifts only" },
                { value: "medical",    label: "🏥 Medical",    desc: "Nearest medical centre" },
              ] as { value: AccessibilityPreference; label: string; desc: string }[]
            ).map(({ value, label, desc }) => (
              <label
                key={value}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.375rem",
                  cursor: "pointer",
                  color: accessibility === value ? "#93c5fd" : "#94a3b8",
                  fontSize: "0.9375rem",
                }}
              >
                <input
                  type="radio"
                  name="accessibility"
                  value={value}
                  checked={accessibility === value}
                  onChange={() => setAccessibility(value)}
                  aria-describedby={`acc-desc-${value}`}
                />
                {label}
                <span
                  id={`acc-desc-${value}`}
                  style={{
                    fontSize: "0.8125rem",
                    color: "#64748b",
                    display: "none", // Hidden — only used by AT via aria-describedby
                  }}
                >
                  {desc}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {/* Inline form error */}
        {formError && (
          <p
            id={errorId}
            role="alert"
            style={{
              margin: 0,
              color: "#f87171",
              fontSize: "0.875rem",
              fontWeight: 500,
            }}
          >
            {formError}
          </p>
        )}

        {/* Submit button */}
        <button
          type="submit"
          disabled={isLoading}
          aria-busy={isLoading}
          aria-label={isLoading ? "Computing route..." : "Get route"}
          style={{
            backgroundColor: isLoading ? "#1e3a5f" : "#2563eb",
            color: "#ffffff",
            border: "none",
            borderRadius: "0.5rem",
            padding: "0.75rem 1.5rem",
            fontSize: "1rem",
            fontWeight: 700,
            cursor: isLoading ? "not-allowed" : "pointer",
            transition: "background-color 0.2s",
            // Minimum touch target 44×44px (WCAG SC 2.5.5)
            minHeight: "44px",
          }}
        >
          {isLoading ? "🔄 Computing..." : "🧭 Get Route"}
        </button>
      </form>

      {/* API error alert */}
      {error && (
        <AlertBanner
          severity="warning"
          message={`Navigation error: ${error.message}`}
          onDismiss={clearRoute}
        />
      )}

      {/* Route results */}
      {route && (
        <div
          aria-live="polite"
          aria-label="Navigation route results"
        >
          {/* Summary */}
          <div
            style={{
              backgroundColor: "#0f172a",
              borderRadius: "0.5rem",
              padding: "0.875rem 1rem",
              marginBottom: "0.75rem",
              display: "flex",
              flexWrap: "wrap",
              gap: "1rem",
            }}
          >
            <span style={{ color: "#94a3b8", fontSize: "0.875rem" }}>
              📏 {route.total_distance_meters.toFixed(0)} m
            </span>
            <span style={{ color: "#94a3b8", fontSize: "0.875rem" }}>
              ⏱️ ~{Math.ceil(route.total_estimated_seconds / 60)} min
            </span>
            {route.is_crowd_optimized && (
              <span
                style={{
                  color: "#4ade80",
                  fontSize: "0.875rem",
                  fontWeight: 600,
                }}
                aria-label="Route was optimized to avoid congested areas"
              >
                ✓ Crowd-Optimized
              </span>
            )}
          </div>

          {/* Step list */}
          <ol
            ref={resultsRef}
            aria-label={`Navigation route: ${route.steps.length} steps`}
            style={{
              margin: 0,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: "0.5rem",
            }}
          >
            {route.steps.map((step, idx) => (
              <RouteStep
                key={step.step_number}
                step={step}
                isCurrent={idx === 0}
                isRtl={isRtl}
                warningId={`crowd-warn-${step.step_number}`}
              />
            ))}
          </ol>
        </div>
      )}
    </section>
  );
};
