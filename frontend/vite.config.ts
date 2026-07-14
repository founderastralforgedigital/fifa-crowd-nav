import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Vite configuration for FIFA 2026 Fan Navigator.
 *
 * Server proxy: During development, all /api/* and /health requests are
 * proxied to the FastAPI backend at localhost:8000. This avoids CORS
 * issues without configuring the backend ALLOWED_ORIGINS for localhost.
 */
export default defineConfig({
  plugins: [react()],

  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },

  build: {
    // Target modern browsers only — FIFA 2026 fans will have current browsers
    target: "es2022",
    // Split vendor chunks for better caching
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          axios: ["axios"],
        },
      },
    },
  },
});
