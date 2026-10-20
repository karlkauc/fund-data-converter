import { defineConfig, devices } from "@playwright/test";

const port = process.env.E2E_PORT ?? "8090";
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL, trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.spec\.ts/ },
    // Phone and tablet run only the responsive spec, with Chromium's device emulation.
    { name: "phone", use: { ...devices["iPhone 13"], browserName: "chromium" }, testMatch: /mobile\.spec\.ts/ },
    { name: "tablet", use: { ...devices["iPad (gen 7)"], browserName: "chromium" }, testMatch: /mobile\.spec\.ts/ },
  ],
  // E2E_EXTERNAL=1: a server is already running (e.g. `docker run`); otherwise boot the backend in place.
  webServer: process.env.E2E_EXTERNAL
    ? undefined
    : {
        command:
          "cd ../backend && STATIC_DIR=../frontend/dist TRUSTED_PROXY_HOPS=0 CONVERT_RATE_LIMIT=1000/minute " +
          "uvicorn app.main:app --host 127.0.0.1 --port " + port,
        url: baseURL + "/api/health",
        reuseExistingServer: !process.env.CI,
        timeout: 30_000,
      },
});
