/**
 * components/AlertBanner/AlertBanner.tsx — WCAG 2.1 AA compliant alert banner.
 *
 * Accessibility features:
 * - aria-live="assertive": Screen readers interrupt current speech for CRITICAL alerts.
 * - aria-live="polite": For informational alerts, waits for a pause before announcing.
 * - role="alert": Explicitly marks the region as an alert for assistive technologies.
 * - aria-atomic="true": The entire message is re-read when updated, not just the diff.
 * - High contrast colors meeting WCAG AA 4.5:1 minimum for normal text.
 * - Keyboard dismissible via Escape key.
 */

import React, { useEffect, useRef } from "react";

export type AlertSeverity = "info" | "warning" | "critical";

interface AlertBannerProps {
  readonly message: string;
  readonly severity: AlertSeverity;
  readonly onDismiss?: () => void;
  /** Optional ID for aria-describedby associations from other elements */
  readonly id?: string;
}

const SEVERITY_STYLES: Record<AlertSeverity, React.CSSProperties> = {
  info: {
    backgroundColor: "#1e3a5f",
    color: "#e0f2fe",
    borderLeft: "4px solid #38bdf8",
  },
  warning: {
    backgroundColor: "#78350f",
    color: "#fef3c7",
    borderLeft: "4px solid #fbbf24",
  },
  critical: {
    backgroundColor: "#7c2d12",
    color: "#fde68a",
    borderLeft: "6px solid #ef4444",
  },
};

const SEVERITY_ICONS: Record<AlertSeverity, string> = {
  info:     "ℹ️",
  warning:  "⚠️",
  critical: "🚨",
};

export const AlertBanner: React.FC<AlertBannerProps> = ({
  message,
  severity,
  onDismiss,
  id,
}) => {
  const bannerRef = useRef<HTMLDivElement>(null);

  // Handle Escape key to dismiss — keyboard accessibility (WCAG 2.1 SC 2.1.1)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onDismiss) {
        onDismiss();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onDismiss]);

  // Move focus to the banner when a CRITICAL alert appears so keyboard users
  // are immediately aware (WCAG 2.1 SC 2.4.3 — Focus Order)
  useEffect(() => {
    if (severity === "critical" && bannerRef.current) {
      bannerRef.current.focus();
    }
  }, [severity, message]);

  return (
    <div
      id={id}
      ref={bannerRef}
      role="alert"
      aria-live={severity === "critical" ? "assertive" : "polite"}
      aria-atomic="true"
      tabIndex={-1} // focusable programmatically but not in tab order
      style={{
        ...SEVERITY_STYLES[severity],
        display: "flex",
        alignItems: "flex-start",
        gap: "0.75rem",
        padding: "0.875rem 1.25rem",
        borderRadius: "0.375rem",
        fontSize: "0.9375rem",
        fontWeight: severity === "critical" ? 700 : 500,
        lineHeight: 1.5,
        outline: "none", // focus handled via programmatic focus, not visible ring here
      }}
    >
      <span aria-hidden="true" style={{ fontSize: "1.25rem", flexShrink: 0 }}>
        {SEVERITY_ICONS[severity]}
      </span>

      <span style={{ flex: 1 }}>{message}</span>

      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss alert"
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "inherit",
            fontSize: "1.25rem",
            padding: "0 0.25rem",
            lineHeight: 1,
            opacity: 0.8,
            flexShrink: 0,
          }}
        >
          ×
        </button>
      )}
    </div>
  );
};
