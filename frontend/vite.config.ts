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
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        // Recharts pulls in most of d3 and dominates the bundle. Splitting it
        // out means the shell and the first paint don't wait on charting code
        // that only three routes need.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
        },
      },
    },
  },
});
