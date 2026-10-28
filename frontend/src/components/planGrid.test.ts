import { describe, expect, it } from "vitest";
import type { PlanResponse } from "../api/client";
import { excludedNotice } from "./planRows";
import {
  budgetFromNeed,
  digitsOnly,
  formatBudgetInput,
  overridesFromEdits,
  rowsFromPlan,
} from "./planRows";

const plan = {
  visits: [
    {
      tid: "1001",
      date: "2026-03-10",
      kind: "scheduled",
      recommended: 500_000_000,
      allocated: 400_000_000,
      override: null,
      tier1_need: 500_000_000,
      reason: "Scheduled visit",
      flags: ["underfunded"],
      manual: false,
    },
    {
      tid: "1002",
      date: "2026-03-12",
      kind: "moved",
      recommended: 100_000_000,
      allocated: 100_000_000,
      override: { amount: null, skipped: false, moved_from: "2026-03-11" },
      tier1_need: 0,
      reason: "Scheduled visit",
      flags: [],
      manual: true,
    },
  ],
} as unknown as PlanResponse;
const names = { "1001": "Terminal Station", "1002": "Mall X" };

describe("rowsFromPlan", () => {
  it("maps visits to rows with a stable key, location and skip flag", () => {
    const rows = rowsFromPlan(plan, names);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ key: "1001|2026-03-10", location: "Terminal Station", amount: 400_000_000, skip: false });
  });
});

describe("overridesFromEdits", () => {
  const rows = rowsFromPlan(plan, names);

  it("an amount edit makes one override with that tid/date/amount", () => {
    const o = overridesFromEdits([rows[0]], { "1001|2026-03-10": { amount: 250_000_000 } });
    expect(o).toEqual([
      { tid: "1001", visit_date: "2026-03-10", amount: 250_000_000, skipped: false, moved_from: null },
    ]);
  });

  it("toggling skip sends skipped: true", () => {
    const o = overridesFromEdits([rows[0]], { "1001|2026-03-10": { skip: true } });
    expect(o).toHaveLength(1);
    expect(o[0]).toMatchObject({ tid: "1001", visit_date: "2026-03-10", skipped: true });
  });

  it("a date edit records moved_from and keeps existing overrides of other rows", () => {
    const o = overridesFromEdits(rows, { "1001|2026-03-10": { date: "2026-03-11" } });
    expect(o).toHaveLength(2);
    expect(o.find((x) => x.tid === "1001")).toMatchObject({ visit_date: "2026-03-11", moved_from: "2026-03-10" });
    expect(o.find((x) => x.tid === "1002")).toMatchObject({ visit_date: "2026-03-12", moved_from: "2026-03-11" });
  });

  it("un-skipping a skipped row leaves it out of the set (the PUT replaces the window)", () => {
    const skipped = { ...rows[0], skip: true, manual: true, override: { amount: null, skipped: true, moved_from: null } };
    expect(overridesFromEdits([skipped], { "1001|2026-03-10": { skip: false } })).toEqual([]);
  });

  it("moving a moved visit back to its original date drops its override", () => {
    expect(overridesFromEdits([rows[1]], { "1002|2026-03-12": { date: "2026-03-11" } })).toEqual([]);
  });

  it("moving a moved visit again keeps the original moved_from", () => {
    expect(overridesFromEdits([rows[1]], { "1002|2026-03-12": { date: "2026-03-13" } })).toEqual([
      { tid: "1002", visit_date: "2026-03-13", amount: null, skipped: false, moved_from: "2026-03-11" },
    ]);
  });
});

describe("budget helpers", () => {
  it("digitsOnly strips everything but digits", () => expect(digitsOnly("7.000,5abc")).toBe("70005"));
  it("formats with id-ID grouping", () => expect(formatBudgetInput("7000000000")).toBe("7.000.000.000"));
  it("70% of need rounds down to 100.000", () => expect(budgetFromNeed(10_123_456_789)).toBe(7_086_400_000));
});

describe("excludedNotice", () => {
  it("lists the TIDs left out of the plan (forecast failed / insufficient history)", () => {
    const atms = [
      { tid: "1001", status: "ok" },
      { tid: "1003", status: "forecast_failed" },
      { tid: "1002", status: "insufficient_history" },
    ];
    expect(excludedNotice(atms)).toBe(
      "Not in the plan: 1003 (forecast failed), 1002 (insufficient history).",
    );
    expect(excludedNotice([{ tid: "1001", status: "ok" }])).toBeNull();
    expect(excludedNotice(undefined)).toBeNull();
  });
});
