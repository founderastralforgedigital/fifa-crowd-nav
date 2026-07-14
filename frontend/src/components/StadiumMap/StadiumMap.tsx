/**
 * components/StadiumMap/StadiumMap.tsx — Stadium zone density overview.
 *
 * WCAG 2.1 AA compliance:
 * - role="list" on container with role="listitem" on each ZoneIndicator.
 * - aria-label on the outer section describes the purpose.
 * - Loading state uses aria-busy and a visually hidden loading text.
 * - Bottleneck summary uses aria-live="assertive" for critical alerts.
 * - Skip link allows keyboard users to jump past the zone list.
 */

import React from "react";
import type { StadiumCrowdSnapshot } from "../../types/api";
import { DENSITY_COLORS } from "../../types/api";
import { AlertBanner } from "../AlertBanner/AlertBanner";
import { ZoneIndicator } from "./ZoneIndicator";

interface StadiumMapProps {
  readonly snapshot: StadiumCrowdSnapshot | null;
  readonly isLoading: boolean;
  readonly stadiumName: string;
}

export const StadiumMap: React.FC<StadiumMapProps> = ({
  snapshot,
  isLoading,
  stadiumName,
}) => {
  const hasCritical = snapshot?.active_bottleneck_zone_ids.length
    ? snapshot.zones.some((z) => z.density_level === "critical")
    : false;

  return (
    <section aria-labelledby="crowd-map-heading" aria-busy={isLoading}>
      {/* Skip link — allows keyboard users to jump to navigation panel */}
      <a
        href="#navigation-panel"
        style={{
          position: "absolute",
          left: "-9999px",
          top: "auto",
          width: "1px",
          height: "1px",
          overflow: "hidden",
        }}
        onFocus={(e) => {
          e.currentTarget.style.left = "1rem";
          e.currentTarget.style.width = "auto";
          e.currentTarget.style.height = "auto";
        }}
        onBlur={(e) => {
          e.currentTarget.style.left = "-9999px";
          e.currentTarget.style.width = "1px";
          e.currentTarget.style.height = "1px";
        }}
      >
        Skip to Navigation Panel
      </a>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: "1rem",
          flexWrap: "wrap",
          gap: "0.5rem",
        }}
      >
        <h2 id="crowd-map-heading" style={{ margin: 0, fontSize: "1.25rem", color: "#f1f5f9" }}>
          🏟️ {stadiumName} — Live Crowd
        </h2>

        {snapshot && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              fontSize: "0.875rem",
              color: "#94a3b8",
            }}
            aria-label={`Overall stadium density: ${snapshot.overall_density_level}`}
          >
            <span style={{ fontWeight: 600 }}>Overall:</span>
            <span
              style={{
                backgroundColor: DENSITY_COLORS[snapshot.overall_density_level].bg,
                color: DENSITY_COLORS[snapshot.overall_density_level].fg,
                padding: "0.15rem 0.5rem",
                borderRadius: "0.25rem",
                fontWeight: 700,
                fontSize: "0.875rem",
              }}
            >
              {DENSITY_COLORS[snapshot.overall_density_level].label}
            </span>
            <span>
              {snapshot.total_occupancy.toLocaleString()} /
              {snapshot.total_capacity.toLocaleString()} fans
            </span>
          </div>
        )}
      </div>

      {/* Critical bottleneck alert */}
      {hasCritical && snapshot && (
        <AlertBanner
          severity="critical"
          message={`🚨 Critical congestion in ${snapshot.active_bottleneck_zone_ids.length} zone(s). Please follow staff instructions and use alternate exits.`}
        />
      )}

      {/* Loading state */}
      {isLoading && !snapshot && (
        <div
          aria-label="Loading crowd data"
          style={{
            textAlign: "center",
            padding: "2rem",
            color: "#94a3b8",
            fontSize: "1rem",
          }}
        >
          <span aria-hidden="true">⏳</span> Loading crowd data...
        </div>
      )}

      {/* Zone list */}
      {snapshot && (
        <div
          role="list"
          aria-label={`Stadium zones — ${snapshot.zones.length} zones shown`}
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
            gap: "0.625rem",
          }}
        >
          {snapshot.zones.map((zone) => (
            <ZoneIndicator
              key={zone.zone_id}
              zone={zone}
              isBottleneck={snapshot.active_bottleneck_zone_ids.includes(zone.zone_id)}
            />
          ))}
        </div>
      )}
    </section>
  );
};
