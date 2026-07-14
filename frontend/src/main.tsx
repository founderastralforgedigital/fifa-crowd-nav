/**
 * main.tsx — React application entry point.
 *
 * Renders the App inside React.StrictMode to surface deprecated API usage
 * and double-invocation checks during development.
 *
 * The <meta> tags in index.html (SEO + accessibility) are required alongside:
 * - lang attribute on <html>: set dynamically by LanguageSelector
 * - viewport: width=device-width,initial-scale=1 (no user-scalable=no — WCAG SC 1.4.4)
 */

import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/global.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error(
    "Root element #root not found in index.html. Cannot mount React application."
  );
}

createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
