// import { defineConfig } from "vite";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// /api is proxied to the FastAPI backend in dev; in the demo FastAPI serves dist/ itself.
// export default defineConfig({
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  // the backend port follows CASHFC_PORT (scripts\dev.ps1 passes it on), default 8000
  server: { port: 5173, proxy: { "/api": `http://127.0.0.1:${loadEnv(mode, ".", "").CASHFC_PORT || "8000"}` } },
  // });
}));
