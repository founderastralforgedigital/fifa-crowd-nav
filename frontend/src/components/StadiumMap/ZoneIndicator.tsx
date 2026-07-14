/**
 * components/StadiumMap/ZoneIndicator.tsx — Crowd density zone indicator.
 *
 * WCAG 2.1 AA compliance:
 * - Color is NEVER the sole means of conveying density status (SC 1.4.1).
 *   Each zone shows: color badge + text label + icon.
 * - Contrast ratios meet WCAG AA (4.5:1 normal text, 3:1 large/bold text).
 * - Critical zones pulse with a CSS animation to attract attention without
 *   relying solely on color (supports color-blind users).
 * - aria-label provides a complete spoken description for screen readers.
 */

import React from "react";
import type { ZoneCrowdState } from "../../types/api";
import { DENSITY_COLORS } from "../../types/api";

interface ZoneIndicatorProps {
  readonly zone: ZoneCrowdState;
  readonly isBottleneck: boolean;
}

const DENSITY_ICONS: Record<string, string> = {
  low:      "🟢",
  medium:   "🟡",
  high:     "🔴",
  critical: "🚨",
};

export const ZoneIndicator: React.FC<ZoneIndicatorProps> = ({ zone, isBottleneck }) => {
  const colors = DENSITY_COLORS[zone.density_level];
  const icon = DENSITY_ICONS[zone.density_level];
  const occupancyPct = Math.round(zone.density_score * 100);

  // Accessible description read by screen readers:
  // "North Concourse: High density, 78% capacity. Bottleneck detected."
  const ariaLabel = [
    `${zone.zone_name}:`,
    `${colors.label} density,`,
    `${occupancyPct}% capacity.`,
    isBottleneck ? "Bottleneck detected." : "",
    `15-minute prediction: ${DENSITY_COLORS[zone.predicted_density_in_15min].label}.`,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      role="listitem"
      aria-label={ariaLabel}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.625rem",
        padding: "0.625rem 0.875rem",
        borderRadius: "0.5rem",
        backgroundColor: "#1e293b",
        border: isBottleneck
          ? "1px solid rgba(239,68,68,0.6)"
          : "1px solid #334155",
        // Critical zones pulse to draw attention without relying only on color
        animation:
          zone.density_level === "critical"
            ? "pulse 1.5s cubic-bezier(0.4,0,0.6,1) infinite"
            : "none",
      }}
    >
      {/* Icon — aria-hidden since the ariaLabel above covers it */}
      <span aria-hidden="true" style={{ fontSize: "1.1rem" }}>
        {icon}
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Zone name — truncated with ellipsis to preserve layout */}
        <p
          style={{
            margin: 0,
            fontWeight: 600,
            fontSize: "0.875rem",
            color: "#f1f5f9",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {zone.zone_name}
        </p>

        {/* Capacity bar — visual supplement, not sole density indicator */}
        <div
          aria-hidden="true"
          style={{
            marginTop: "0.25rem",
            height: "4px",
            borderRadius: "2px",
            backgroundColor: "#334155",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${occupancyPct}%`,
              height: "100%",
              backgroundColor: colors.bg,
              transition: "width 0.6s ease",
            }}
          />
        </div>
      </div>

      {/* Text density badge — redundant with color, satisfies WCAG SC 1.4.1 */}
      <span
        style={{
          backgroundColor: colors.bg,
          color: colors.fg,
          fontSize: "0.75rem",
          fontWeight: 700,
          padding: "0.15rem 0.5rem",
          borderRadius: "0.25rem",
          whiteSpace: "nowrap",
          flexShrink: 0,
        }}
      >
        {occupancyPct}%
      </span>
    </div>
  );
};
