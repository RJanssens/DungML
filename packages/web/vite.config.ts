import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

// Build into the backend's static dir so a single FastAPI process can serve
// the SPA in production.
const here = fileURLToPath(new URL(".", import.meta.url));
const backendStatic = resolve(
  here,
  "../backend/src/dungml_backend/static",
);

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: backendStatic,
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
