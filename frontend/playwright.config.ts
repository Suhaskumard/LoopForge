import { defineConfig, devices } from "@playwright/test";

// Real browser, real API (the scripted demo server: no API key or Docker needed), real Vite dev server.
const python =
  process.env.PYTHON ?? (process.platform === "win32" ? "..\\.venv\\Scripts\\python.exe" : "../.venv/bin/python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false, // one shared demo server and database
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: [
    {
      command: `${python} ../scripts/dev_demo_server.py`,
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { PORT: "8000", DEMO_DELAY: "0.05", E2E: "1" },
    },
    {
      command: "npx vite --host 127.0.0.1 --port 5173",
      url: "http://127.0.0.1:5173",
      // Never reuse: a leftover `npm run dev` has VITE_DEV_AUTOLOGIN=1 and would sign every test in as the demo user.
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_BACKEND: "http://127.0.0.1:8000", VITE_DEV_AUTOLOGIN: "0" }, // no dev auto-login: tests sign in themselves
    },
  ],
});
