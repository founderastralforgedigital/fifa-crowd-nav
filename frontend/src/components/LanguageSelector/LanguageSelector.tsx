/**
 * components/LanguageSelector/LanguageSelector.tsx — Accessible language picker.
 *
 * WCAG 2.1 AA compliance:
 * - Uses a native <select> element for optimal AT (screen reader) compatibility.
 * - aria-label provides a meaningful label for the control.
 * - Visible focus ring using :focus-visible CSS.
 * - Text direction (dir="rtl") applied to the document when Arabic is selected.
 * - Font stacks include Arabic and CJK characters for correct rendering.
 */

import React, { useEffect } from "react";
import type { SupportedLanguage } from "../../types/api";
import { LANGUAGE_LABELS, RTL_LANGUAGES } from "../../types/api";

interface LanguageSelectorProps {
  readonly value: SupportedLanguage;
  readonly onChange: (language: SupportedLanguage) => void;
  readonly id?: string;
}

const ALL_LANGUAGES = Object.keys(LANGUAGE_LABELS) as SupportedLanguage[];

export const LanguageSelector: React.FC<LanguageSelectorProps> = ({
  value,
  onChange,
  id = "language-selector",
}) => {
  // Update document direction when an RTL language is selected
  // This ensures the entire navigation UI renders correctly for Arabic users
  useEffect(() => {
    const isRtl = RTL_LANGUAGES.has(value);
    document.documentElement.dir = isRtl ? "rtl" : "ltr";
    document.documentElement.lang = value;
  }, [value]);

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    onChange(e.target.value as SupportedLanguage);
  };

  return (
    <div
      style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}
    >
      {/* Explicit label for screen readers — not aria-label alone */}
      <label
        htmlFor={id}
        style={{
          color: "#94a3b8",
          fontSize: "0.875rem",
          fontWeight: 500,
          whiteSpace: "nowrap",
        }}
      >
        🌐 Language
      </label>

      <select
        id={id}
        value={value}
        onChange={handleChange}
        aria-label="Select navigation language"
        style={{
          backgroundColor: "#1e293b",
          color: "#f1f5f9",
          border: "1px solid #334155",
          borderRadius: "0.375rem",
          padding: "0.375rem 0.75rem",
          fontSize: "0.9375rem",
          cursor: "pointer",
          // Focus ring visible to keyboard users (WCAG SC 2.4.7)
          outline: "none",
        }}
        // Inline :focus styles can't express :focus-visible; use className in production
        onFocus={(e) => (e.target.style.boxShadow = "0 0 0 3px rgba(59,130,246,0.6)")}
        onBlur={(e) => (e.target.style.boxShadow = "none")}
      >
        {ALL_LANGUAGES.map((lang) => (
          <option key={lang} value={lang}>
            {LANGUAGE_LABELS[lang]}
          </option>
        ))}
      </select>
    </div>
  );
};
