/**
 * components/NavigationPanel/RouteStep.tsx — A single navigable route step.
 *
 * WCAG 2.1 AA compliance:
 * - Each step is a proper list item (<li>) within a semantic <ol>.
 * - aria-current="step" marks the currently visible step for AT users.
 * - Crowd warnings are linked to the step via aria-describedby.
 * - Focus styles are visible (WCAG SC 2.4.7 — Focus Visible).
 * - Time estimates use <time> element for semantic HTML5.
 */

import React from "react";
import type { RouteStep as RouteStepType } from "../../types/api";

interface RouteStepProps {
  readonly step: RouteStepType;
  readonly isCurrent: boolean;
  readonly isRtl: boolean;
  readonly warningId: string;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

export const RouteStep: React.FC<RouteStepProps> = ({
  step,
  isCurrent,
  isRtl,
  warningId,
}) => {
  return (
    <li
      aria-current={isCurrent ? "step" : undefined}
      aria-describedby={step.crowd_warning ? warningId : undefined}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.375rem",
        padding: "0.875rem 1rem",
        borderRadius: "0.5rem",
        backgroundColor: isCurrent ? "#1e3a5f" : "#1e293b",
        border: isCurrent ? "1px solid #3b82f6" : "1px solid #334155",
        listStyle: "none",
        // Ensure focus ring visible on keyboard navigation (WCAG SC 2.4.7)
        outline: isCurrent ? "2px solid #3b82f6" : "none",
        outlineOffset: "2px",
      }}
      dir={isRtl ? "rtl" : "ltr"}
    >
      {/* Step header row */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        {/* Step number badge */}
        <span
          aria-hidden="true"
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "1.75rem",
            height: "1.75rem",
            borderRadius: "50%",
            backgroundColor: isCurrent ? "#3b82f6" : "#334155",
            color: "#ffffff",
            fontSize: "0.8125rem",
            fontWeight: 700,
            flexShrink: 0,
          }}
        >
          {step.step_number}
        </span>

        {/* Zone name */}
        <span
          style={{
            fontWeight: 600,
            fontSize: "0.9375rem",
            color: "#f1f5f9",
          }}
        >
          {step.zone_name}
        </span>

        {/* Accessible indicator */}
        {step.is_accessible_route && (
          <span
            title="Accessible route — no stairs"
            aria-label="Accessible route"
            style={{ marginLeft: "auto", fontSize: "1rem" }}
          >
            ♿
          </span>
        )}

        {/* Time estimate */}
        {step.estimated_seconds > 0 && (
          <time
            dateTime={`PT${step.estimated_seconds}S`}
            style={{
              marginLeft: "auto",
              fontSize: "0.8125rem",
              color: "#94a3b8",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            ~{formatDuration(step.estimated_seconds)}
          </time>
        )}
      </div>

      {/* GenAI localized instruction */}
      <p
        style={{
          margin: 0,
          fontSize: "0.9375rem",
          color: "#cbd5e1",
          lineHeight: 1.5,
          paddingLeft: "2.5rem", // Align with text after step number
        }}
      >
        {step.instruction}
      </p>

      {/* Crowd warning — linked via aria-describedby */}
      {step.crowd_warning && (
        <p
          id={warningId}
          role="alert"
          aria-live="polite"
          style={{
            margin: 0,
            fontSize: "0.875rem",
            color: "#fbbf24",
            backgroundColor: "rgba(217,119,6,0.15)",
            padding: "0.375rem 0.625rem",
            borderRadius: "0.25rem",
            borderLeft: "3px solid #f59e0b",
          }}
        >
          {step.crowd_warning}
        </p>
      )}
    </li>
  );
};
