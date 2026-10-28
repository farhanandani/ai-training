import { expect, test, type Page } from "@playwright/test";

// Tests share one server + workspace DB and run in file order; the edit test mutates data, so it stays last.
test.describe.configure({ mode: "serial" });

const ROUTES = ["/", "/planner", "/data", "/accuracy", "/atm/TID-JKT-0001"];
const FIRST_LOAD_MS = 120_000;

/** Fleet fully loaded: all 10 ATM rows present and the "Forecasting ..." progress gone. */
async function fleetReady(page: Page) {
  await expect(page.getByRole("link", { name: /Details/ })).toHaveCount(10, { timeout: FIRST_LOAD_MS });
  await expect(page.getByText(/^Forecasting \d+(\/| more)/)).toHaveCount(0, { timeout: FIRST_LOAD_MS });
}

test("all routes render without console errors (AC2)", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()}`));
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  for (const r of ROUTES) {
    await page.goto(r);
    await expect(page.getByRole("banner")).toBeVisible();
    await page.waitForLoadState("networkidle", { timeout: FIRST_LOAD_MS });
    if (r === "/") await fleetReady(page);
  }
  expect(problems).toEqual([]);
});

test("pre-lebaran shows risk and overstock (AC9)", async ({ page }) => {
  await page.goto("/");
  await fleetReady(page);
  expect(await page.getByText("Cash-out risk", { exact: true }).count()).toBeGreaterThanOrEqual(1);
  expect(await page.getByText("Over-stocked", { exact: true }).count()).toBeGreaterThanOrEqual(1);
});

test("planner reallocation at 70% (AC9)", async ({ page }) => {
  await page.goto("/planner");
  await page.getByRole("button", { name: "70% of need" }).click();
  const count = page.getByTestId("sankey-links-count").last();
  await expect
    .poll(async () => Number((await count.textContent()) ?? "0"), { timeout: FIRST_LOAD_MS })
    .toBeGreaterThan(0);
});

test("no network requests leave 127.0.0.1:8123 across all routes (TR-04 offline evidence)", async ({ page }) => {
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  for (const r of ROUTES) {
    await page.goto(r);
    await page.waitForLoadState("networkidle", { timeout: FIRST_LOAD_MS });
  }
  const external = urls.filter((u) => !/^(data|blob|about):/.test(u) && new URL(u).host !== "127.0.0.1:8123");
  expect(urls.length).toBeGreaterThan(5);
  expect(external).toEqual([]);
});

test("edit recompute (AC5)", async ({ page }) => {
  const tid = "TID-JKT-0001";
  await page.goto("/");
  await fleetReady(page);
  const amount = () => page.getByRole("row").filter({ hasText: tid }).locator("td").nth(5);
  const before = (await amount().textContent()) ?? "";
  expect(before).toMatch(/\d/);

  // as-of day of the default scenario: the closing balance there is the ATM's current balance
  await page.getByRole("link", { name: "Data", exact: true }).click();
  await page.getByLabel("TID", { exact: true }).selectOption(tid);
  await page.getByLabel("From date").fill("2026-03-06");
  await page.getByLabel("To date").fill("2026-03-06");
  const cell = page.locator('.ag-row [col-id="closing_balance"]').first();
  await expect(cell).toBeVisible();
  await cell.dblclick();
  await page.keyboard.press("Control+A");
  await page.keyboard.type("1000000");
  await page.keyboard.press("Enter");

  await page.getByRole("button", { name: /Save changes/ }).click();
  const t0 = Date.now();
  await page.getByRole("link", { name: "Fleet", exact: true }).click();
  await expect.poll(async () => (await amount().textContent()) ?? "", { timeout: 10_000 }).not.toBe(before);
  await expect(page.getByText(/^Forecasting \d+(\/| more)/)).toHaveCount(0, { timeout: 10_000 });
  const after = ((await amount().textContent()) ?? "").trim();
  console.log(`AC5: recommended amount ${before.trim()} -> ${after} in ${Date.now() - t0} ms after save`);
});
