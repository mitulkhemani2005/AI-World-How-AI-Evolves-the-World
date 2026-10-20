import { defineConfig } from "vite";

// The Vite app stays independent; API requests are proxied to FastAPI during development.
export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    // Keep Three.js in a cacheable vendor chunk separate from the small UI module.
    rollupOptions: { output: { manualChunks: { "three-vendor": ["three"] } } },
  },
});
