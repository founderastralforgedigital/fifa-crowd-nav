/**
 * App.tsx — Root application component for FIFA 2026 Crowd Navigation.
 *
 * Orchestrates:
 * - Stadium selection (dropdown from all 16 host cities)
 * - Language selection (10 languages, RTL support)
 * - Real-time crowd data display (StadiumMap)
 * - Navigation panel (NavigationPanel)
 *
 * WCAG 2.1 AA compliance:
 * - Landmark regions: <header>, <main>, <nav> (implicit in LanguageSelector).
 * - Skip navigation link at the top of the page.
 * - Color contrast: background #0f172a (dark navy) with white text.
 * - Font: Inter (system fallback) — legible at all sizes.
 * - Responsive: single-column on mobile, two-column on wider screens.
 */

import React, { useEffect, useState } from "react";
import { fetchStadium, fetchStadiums } from "./services/apiClient";
import { LanguageSelector } from "./components/LanguageSelector/LanguageSelector";
import { NavigationPanel } from "./components/NavigationPanel/NavigationPanel";
import { StadiumMap } from "./components/StadiumMap/StadiumMap";
import { useCrowdData } from "./hooks/useCrowdData";
import type { Stadium, StadiumSummary, SupportedLanguage } from "./types/api";

export const App: React.FC = () => {
  const [stadiums, setStadiums] = useState<StadiumSummary[]>([]);
  const [selectedStadiumId, setSelectedStadiumId] = useState<string | null>(null);
  const [selectedStadium, setSelectedStadium] = useState<Stadium | null>(null);
  const [language, setLanguage] = useState<SupportedLanguage>("en");
  const [loadError, setLoadError] = useState<string>("");

  const { snapshot, isLoading: crowdLoading } = useCrowdData(selectedStadiumId);

  // Load stadium list on mount
  useEffect(() => {
    fetchStadiums()
      .then(setStadiums)
      .catch(() =>
        setLoadError("Unable to load stadium list. Please try again.")
      );
  }, []);

  // Load full stadium details when selection changes
  useEffect(() => {
    if (!selectedStadiumId) {
      setSelectedStadium(null);
      return;
    }
    fetchStadium(selectedStadiumId)
      .then(setSelectedStadium)
      .catch(() => setLoadError("Unable to load stadium details."));
  }, [selectedStadiumId]);

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "#0f172a",
        color: "#f1f5f9",
        fontFamily:
          "'Inter', 'Segoe UI', system-ui, -apple-system, 'Noto Sans', sans-serif",
      }}
    >
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <header
        style={{
          backgroundColor: "#0d1b2e",
          borderBottom: "1px solid #1e3a5f",
          padding: "0.875rem 1.5rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
          flexWrap: "wrap",
          position: "sticky",
          top: 0,
          zIndex: 100,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {/* Logo / Brand */}
          <span
            aria-hidden="true"
            style={{ fontSize: "1.75rem", lineHeight: 1 }}
          >
            ⚽
          </span>
          <div>
            <h1
              style={{
                margin: 0,
                fontSize: "1.1875rem",
                fontWeight: 800,
                color: "#f1f5f9",
                lineHeight: 1.2,
              }}
            >
              FIFA 2026 Fan Navigator
            </h1>
            <p
              style={{
                margin: 0,
                fontSize: "0.75rem",
                color: "#64748b",
                fontWeight: 500,
              }}
            >
              GenAI-Powered Crowd-Safe Stadium Navigation
            </p>
          </div>
        </div>

        {/* Language selector — top right, always visible */}
        <LanguageSelector
          id="header-language"
          value={language}
          onChange={setLanguage}
        />
      </header>

      {/* ── Main Content ──────────────────────────────────────────────────── */}
      <main
        id="main-content"
        style={{
          maxWidth: "1280px",
          margin: "0 auto",
          padding: "1.5rem",
          display: "flex",
          flexDirection: "column",
          gap: "1.5rem",
        }}
      >
        {/* Error banner */}
        {loadError && (
          <div role="alert" style={{ color: "#f87171", fontWeight: 600 }}>
            {loadError}
          </div>
        )}

        {/* Stadium selector */}
        <section aria-labelledby="stadium-heading">
          <h2
            id="stadium-heading"
            style={{
              margin: "0 0 0.75rem 0",
              fontSize: "1rem",
              fontWeight: 600,
              color: "#94a3b8",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            Select Stadium
          </h2>
          <select
            id="stadium-select"
            aria-label="Select a FIFA 2026 host stadium"
            value={selectedStadiumId ?? ""}
            onChange={(e) => setSelectedStadiumId(e.target.value || null)}
            style={{
              backgroundColor: "#1e293b",
              color: "#f1f5f9",
              border: "1px solid #334155",
              borderRadius: "0.5rem",
              padding: "0.75rem 1rem",
              fontSize: "1rem",
              width: "100%",
              maxWidth: "480px",
            }}
          >
            <option value="">— Choose a stadium —</option>
            {stadiums.map((s) => (
              <option key={s.stadium_id} value={s.stadium_id}>
                {s.name} — {s.city} ({s.country})
              </option>
            ))}
          </select>
        </section>

        {/* Two-column layout when a stadium is selected */}
        {selectedStadium && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
              gap: "1.5rem",
              alignItems: "start",
            }}
          >
            {/* Left: Crowd density map */}
            <StadiumMap
              snapshot={snapshot}
              isLoading={crowdLoading}
              stadiumName={selectedStadium.name}
            />

            {/* Right: Navigation panel */}
            <div id="navigation-panel">
              <NavigationPanel
                stadiumId={selectedStadium.stadium_id}
                zones={selectedStadium.zones}
                language={language}
              />
            </div>
          </div>
        )}

        {/* Empty state */}
        {!selectedStadium && (
          <div
            aria-live="polite"
            style={{
              textAlign: "center",
              padding: "4rem 2rem",
              color: "#475569",
            }}
          >
            <div aria-hidden="true" style={{ fontSize: "3.5rem", marginBottom: "1rem" }}>
              🏟️
            </div>
            <p style={{ fontSize: "1.125rem", fontWeight: 500 }}>
              Select a stadium above to view live crowd data and get navigation directions.
            </p>
            <p style={{ fontSize: "0.9375rem", marginTop: "0.5rem" }}>
              16 host cities across USA, Canada &amp; Mexico
            </p>
          </div>
        )}
      </main>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <footer
        style={{
          borderTop: "1px solid #1e293b",
          padding: "1rem 1.5rem",
          textAlign: "center",
          color: "#475569",
          fontSize: "0.8125rem",
        }}
      >
        FIFA World Cup 2026 — Crowd Navigation System | 48 teams · 16 cities · 3 countries
      </footer>
    </div>
  );
};

export default App;
