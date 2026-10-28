import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// TR-45/TR-46: end-to-end smoke tests against the real app: uvicorn serving the built SPA + API on one port,
// with a fresh temporary workspace DB per run. Build first (`npm run e2e` does).
const PORT = 8123;
const backend = resolve(process.cwd(), "..", "backend");
const python = join(backend, ".venv", "Scripts", "python.exe");
// const workspaceDb = join(mkdtempSync(join(tmpdir(), "cashfc-e2e-")), "workspace.db");
// config is re-loaded in each worker: create the temp dir once (main process) and share it through the env
process.env.CASHFC_E2E_DB ??= join(mkdtempSync(join(tmpdir(), "cashfc-e2e-")), "workspace.db");
const workspaceDb = process.env.CASHFC_E2E_DB;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 180_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: {
    command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
    cwd: backend,
    url: `http://127.0.0.1:${PORT}/api/context`,
    reuseExistingServer: false,
    timeout: 180_000,
    env: { CASHFC_WORKSPACE_DB: workspaceDb, CASHFC_WARMUP_SCENARIOS: "1", CASHFC_PORT: String(PORT) },
  },
});
