import type { OverridesRequest, PlanResponse } from "../api/client";

export type Override = OverridesRequest["overrides"][number];
export type PlanVisit = PlanResponse["visits"][number];

export interface PlanRow {
  key: string; // tid|original date: stable while the date cell is edited
  tid: string;
  location: string;
  date: string;
  kind: string;
  recommended: number;
  amount: number;
  skip: boolean;
  reason: string;
  flags: string[];
  manual: boolean;
  override: PlanVisit["override"];
}

export interface RowEdit {
  amount?: number;
  skip?: boolean;
  date?: string;
}
export type Edits = Record<string, RowEdit>;

export interface PolicyStats {
  cash_out_days: number;
  idle_cash: number;
  idle_cost: number;
  visits: number;
  visit_cost: number;
  loaded: number;
}
export interface Comparison {
  current: PolicyStats;
  recommended: PolicyStats;
  replay: { basis: "true_demand" | "estimated"; current: PolicyStats; recommended: PolicyStats } | null;
}

// PlanResponse types these two as unknown (backend returns free-form dicts)
export const comparisonOf = (plan: PlanResponse) => plan.comparison as unknown as Comparison;
export const flowsOf = (plan: PlanResponse) =>
  plan.reallocation as { from_tid: string; to_tid: string; amount: number }[];

export function rowsFromPlan(plan: PlanResponse, names: Record<string, string>): PlanRow[] {
  return plan.visits.map((v) => ({
    key: `${v.tid}|${v.date}`,
    tid: v.tid,
    location: names[v.tid] ?? v.tid,
    date: v.date,
    kind: v.kind,
    recommended: v.recommended,
    amount: v.allocated,
    skip: v.flags.includes("skip"),
    reason: v.reason,
    flags: v.flags,
    manual: v.manual,
    override: v.override,
  }));
}

// /** The full override set to PUT: the overrides already on the plan, with the pending cell edits merged in. */
/** The complete override set to PUT for the plan window (the server replaces the window's overrides with it):
 * the overrides already on the plan, with the pending cell edits merged in. */
export function overridesFromEdits(rows: PlanRow[], edits: Edits): Override[] {
  const out: Override[] = [];
  for (const r of rows) {
    const e = edits[r.key];
    if (!e && !r.override) continue;
    const o: Override = {
      tid: r.tid,
      visit_date: r.date,
      amount: r.override?.amount ?? null,
      skipped: r.override?.skipped ?? false,
      moved_from: r.override?.moved_from ?? null,
    };
    if (e?.date !== undefined && e.date !== r.date) {
      o.moved_from = o.moved_from ?? r.date;
      o.visit_date = e.date;
    }
    if (e?.amount !== undefined) {
      o.amount = e.amount;
      o.skipped = false;
    }
    if (e?.skip !== undefined) {
      o.skipped = e.skip;
      if (e.skip) o.amount = null;
    }
    if (o.moved_from === o.visit_date) o.moved_from = null; // moved back to its original date: not a move
    // a no-op override (nothing moved, set or skipped) is dropped
    if (o.skipped || o.amount != null || o.moved_from != null) out.push(o);
  }
  return out;
}

/** Row as shown in the grid: the plan's values with the pending edits on top. */
export function applyEdits(r: PlanRow, e: RowEdit | undefined): PlanRow {
  if (!e) return r;
  return {
    ...r,
    date: e.date ?? r.date,
    amount: e.skip ? 0 : (e.amount ?? r.amount),
    skip: e.skip ?? (e.amount !== undefined ? false : r.skip),
  };
}

export const digitsOnly = (s: string) => s.replace(/\D/g, "");
export const formatBudgetInput = (digits: string) =>
  digits === "" ? "" : new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(Number(digits));
/** floor(70% of need), rounded down to Rp 100.000 */
export const budgetFromNeed = (need: number) => Math.floor((need * 0.7) / 100_000) * 100_000;
