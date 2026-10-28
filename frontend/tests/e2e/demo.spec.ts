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
  const funded = page.getByText("Funded", { exact: true }).locator("xpath=following-sibling::div[1]");
  await expect(funded).toHaveText("100%", { timeout: FIRST_LOAD_MS }); // unconstrained before the click
  await page.getByRole("button", { name: "70% of need" }).click();
  // the click took effect: budget input enabled and filled, Unconstrained unticked, ~70% of need funded
  await expect(page.getByLabel("Unconstrained")).not.toBeChecked();
  const budget = page.getByLabel("Budget (IDR)");
  await expect(budget).toBeEnabled();
  await expect(budget).toHaveValue(/^\d{1,3}(\.\d{3})+$/);
  // (the plan refetches after a 300 ms debounce: wait until funded leaves 100%)
  await expect.poll(async () => (await funded.textContent()) ?? "", { timeout: 30_000 }).not.toBe("100%");
  await expect(page.getByText(/^Budget Rp /)).toBeVisible();
  const pct = Number.parseInt(((await funded.textContent()) ?? "0").replace("%", ""), 10);
  console.log(`Planner 70%: funded ${pct}%`);
  expect(pct).toBeGreaterThanOrEqual(60);
  expect(pct).toBeLessThanOrEqual(80);
  // visible sankey count (the hidden "0" placeholder is excluded)
  // const count = page.getByTestId("sankey-links-count").last();
  // await expect
  //   .poll(async () => Number((await count.textContent()) ?? "0"), { timeout: FIRST_LOAD_MS })
  //   .toBeGreaterThan(0);
  const count = page.locator('[data-testid="sankey-links-count"]:visible');
  await expect(count).toHaveCount(1, { timeout: 30_000 });
  expect(Number(await count.textContent())).toBeGreaterThan(0);
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
  // const amount = () => page.getByRole("row").filter({ hasText: tid }).locator("td").nth(5);
  const col = await page
    .locator("thead th")
    .evaluateAll((ths) => ths.findIndex((t) => /Recommended refill/.test(t.textContent ?? "")));
  expect(col).toBeGreaterThanOrEqual(0);
  const amount = () => page.getByRole("row").filter({ hasText: tid }).locator("td").nth(col);
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

  // wait for the PATCH to be accepted before leaving the page
  const saved = page.waitForResponse(
    (r) => r.url().includes("/api/data/log") && r.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: /Save changes/ }).click();
  const t0 = Date.now();
  expect((await saved).ok()).toBe(true);
  await page.getByRole("link", { name: "Fleet", exact: true }).click();
  await expect.poll(async () => (await amount().textContent()) ?? "", { timeout: 10_000 }).not.toBe(before);
  await expect(page.getByText(/^Forecasting \d+(\/| more)/)).toHaveCount(0, { timeout: 10_000 });
  const after = ((await amount().textContent()) ?? "").trim();
  expect(after).toMatch(/\d/);
  expect(after).not.toBe(before.trim());
  expect(Date.now() - t0).toBeLessThan(10_000); // AC5 budget from the save click
  console.log(`AC5: recommended amount ${before.trim()} -> ${after} in ${Date.now() - t0} ms after save`);
});
