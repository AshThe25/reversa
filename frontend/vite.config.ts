import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The API enforces a same-origin CSP and a non-wildcard CORS allowlist.
    // Proxying in dev keeps the browser on one origin so neither has to be
    // loosened just to make local development work.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
