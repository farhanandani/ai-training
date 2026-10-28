import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useClearOverrides, useFleet, usePlan, useSaveOverrides, useSaveSettings, useSettings } from "../api/hooks";
import { qs } from "../api/client";
import { ComparisonPanel } from "../components/ComparisonPanel";
import { KpiTile } from "../components/KpiTile";
import { PlanGrid } from "../components/PlanGrid";
import { Spinner } from "../components/Spinner";
import { ReallocationSankey } from "../components/charts/ReallocationSankey";
import {
  applyEdits,
  budgetFromNeed,
  comparisonOf,
  digitsOnly,
  flowsOf,
  formatBudgetInput,
  overridesFromEdits,
  rowsFromPlan,
  type Edits,
  type RowEdit,
} from "../components/planRows";
import { formatRp, formatRpCompact } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";
import { useControls } from "../state/controls";

const card = "rounded-lg border border-slate-200 bg-white p-4 shadow-sm";
const btn =
  "rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50";

function SettingsPopover() {
  const { data } = useSettings();
  const save = useSaveSettings();
  const [open, setOpen] = useState(false);
  // drafts are null until the user moves a slider; the saved settings show until then
  const [overDraft, setOver] = useState<number | null>(null);
  const [idleDraft, setIdle] = useState<number | null>(null);
  const over = overDraft ?? (data ? Math.round(data.overstock_frac * 100) : 50); // percent
  const idle = idleDraft ?? (data ? Math.round(data.idle_rate * 1000) / 10 : 5); // percent

  return (
    <div className="relative">
      <button type="button" className={btn} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Settings
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Planner settings"
          className="absolute right-0 z-20 mt-2 w-80 rounded-lg border border-slate-200 bg-white p-4 shadow-lg"
        >
          <label className="block text-sm">
            <span className="flex justify-between text-slate-700">
              Over-stock threshold <b>{over}%</b>
            </span>
            <input
              type="range"
              min={10}
              max={90}
              step={1}
              value={over}
              onChange={(e) => setOver(Number(e.target.value))}
              className="w-full"
            />
            <span className="text-xs text-slate-500">
              Balance above this share of capacity counts as over-stocked (10-90%).
            </span>
          </label>
          <label className="mt-4 block text-sm">
            <span className="flex justify-between text-slate-700">
              Idle-cash rate <b>{idle}%</b>
            </span>
            <input
              type="range"
              min={0}
              max={30}
              step={0.5}
              value={idle}
              onChange={(e) => setIdle(Number(e.target.value))}
              className="w-full"
            />
            <span className="text-xs text-slate-500">Yearly cost of cash sitting idle (0-30%).</span>
          </label>
          {save.isError && <p className="mt-2 text-xs text-red-700">{save.error.message}</p>}
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" className={btn} onClick={() => setOpen(false)}>
              Close
            </button>
            <button
              type="button"
              className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              disabled={save.isPending}
              onClick={() =>
                save.mutate(
                  { overstock_frac: over / 100, idle_rate: idle / 100 },
                  {
                    onSuccess: () => {
                      setOver(null);
                      setIdle(null);
                      setOpen(false);
                    },
                  },
                )
              }
            >
              {save.isPending ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function PlannerPage() {
  const qc = useQueryClient();
  const { asOf, h, sl } = useControls();
  const [unconstrained, setUnconstrained] = useState(true);
  const [digits, setDigits] = useState("");
  const budgetInput = unconstrained || digits === "" ? null : Number(digits);
  const budget = useDebounced(budgetInput, 300);

  const base = usePlan(null); // unconstrained plan: the "70% of need" reference (shares the cache when unconstrained)
  const { data: plan, error, isFetching } = usePlan(budget);
  const fleet = useFleet();
  const names = useMemo(
    () => Object.fromEntries((fleet.data?.atms ?? []).map((a) => [a.tid, a.location_name])),
    [fleet.data?.atms],
  );

  const baseRows = useMemo(() => (plan ? rowsFromPlan(plan, names) : []), [plan, names]);
  const [edits, setEdits] = useState<Edits>({});
  const rows = useMemo(() => baseRows.map((r) => applyEdits(r, edits[r.key])), [baseRows, edits]);

  const saveOverrides = useSaveOverrides();
  const clearOverrides = useClearOverrides();
  const latest = useRef({ baseRows, edits });
  useEffect(() => {
    latest.current = { baseRows, edits };
  });

  // debounced autosave: 300 ms after the last cell edit, PUT the full override set, then refetch the plan
  const pending = useDebounced(edits, 300);
  useEffect(() => {
    const sent = pending;
    if (Object.keys(sent).length === 0 || sent !== latest.current.edits) return;
    const body = { overrides: overridesFromEdits(latest.current.baseRows, sent) };
    saveOverrides.mutate(body, {
      onSuccess: async () => {
        await qc.invalidateQueries({ queryKey: ["plan"] });
        setEdits((cur) => {
          const next = { ...cur };
          for (const k of Object.keys(sent)) if (next[k] === sent[k]) delete next[k];
          return next;
        });
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  const onEdit = useCallback(
    (key: string, e: RowEdit) => setEdits((cur) => ({ ...cur, [key]: { ...cur[key], ...e } })),
    [],
  );

  const onClear = () => clearOverrides.mutate(undefined, { onSuccess: () => setEdits({}) });

  if (error)
    return (
      <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        Could not load the plan: {error.message}
      </div>
    );
  // if (isLoading || !plan) return
  if (!plan) return <Spinner label="Building the allocation plan" />;

  const needBase = base.data?.need_total ?? plan.need_total;
  const hasOverrides = baseRows.some((r) => r.override) || Object.keys(edits).length > 0;
  const flows = flowsOf(plan);
  const pendingTids = plan.pending_tids.length;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiTile label="Total need" value={formatRpCompact(plan.need_total)} hint={`Visits in the next ${plan.h} days`} />
        <KpiTile
          label="Funded"
          value={`${Math.round(plan.funded_pct * 100)}%`}
          tone={plan.funded_pct >= 1 ? "green" : "amber"}
          hint={`${formatRpCompact(plan.funded_total)} of need`}
        />
        <KpiTile
          label="Underfunded visits"
          value={plan.underfunded}
          tone={plan.underfunded ? "red" : "green"}
          hint="Visits that get less than the safe amount"
        />
        <KpiTile
          label="Unused budget"
          value={formatRpCompact(plan.unused)}
          hint={budget === null ? "No budget limit" : "Left after allocation"}
        />
      </div>

      <section className={`${card} flex flex-wrap items-end gap-x-6 gap-y-3`}>
        <div>
          <label htmlFor="budget" className="block text-xs font-medium uppercase tracking-wide text-slate-500">
            Budget (IDR)
          </label>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-sm text-slate-500">Rp</span>
            <input
              id="budget"
              inputMode="numeric"
              className="w-48 rounded border border-slate-300 px-2 py-1.5 text-right text-sm tabular-nums disabled:bg-slate-100 disabled:text-slate-400"
              value={formatBudgetInput(digits)}
              disabled={unconstrained}
              placeholder={unconstrained ? "No limit" : "e.g. 7.000.000.000"}
              onChange={(e) => setDigits(digitsOnly(e.target.value))}
            />
          </div>
          {!unconstrained && digits === "" && (
            <p className="mt-1 text-xs text-amber-700">Enter a budget or tick Unconstrained</p>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={unconstrained} onChange={(e) => setUnconstrained(e.target.checked)} />
          Unconstrained
        </label>
        <button
          type="button"
          className={btn}
          onClick={() => {
            setDigits(String(budgetFromNeed(needBase)));
            setUnconstrained(false);
          }}
        >
          70% of need
        </button>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {isFetching && <span className="text-xs text-slate-500" role="status">Updating&hellip;</span>}
          {hasOverrides && (
            <button type="button" className={btn} onClick={onClear} disabled={clearOverrides.isPending}>
              Clear overrides
            </button>
          )}
          <a className={btn} href={`/api/plan/export.csv${qs({ as_of: asOf, h, sl })}`} download>
            Export CSV
          </a>
          <SettingsPopover />
        </div>
        {(saveOverrides.isError || clearOverrides.isError) && (
          <p role="alert" className="w-full text-sm text-red-700">
            {(saveOverrides.error ?? clearOverrides.error)?.message}
          </p>
        )}
      </section>

      {pendingTids > 0 && (
        <Spinner label={`Forecasting ${pendingTids} more ATM${pendingTids === 1 ? "" : "s"}...`} />
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <section className={card}>
          <h2 className="text-sm font-semibold text-slate-800">Cash moved from over-stocked to at-risk ATMs</h2>
          <p className="mb-2 text-xs text-slate-500">
            {budget === null ? "Unconstrained budget: every ATM is fully funded." : `Budget ${formatRp(budget)}`}
          </p>
          <ReallocationSankey flows={flows} names={names} />
        </section>
        <section className={card}>
          <h2 className="mb-2 text-sm font-semibold text-slate-800">Current policy vs recommended</h2>
          <ComparisonPanel comparison={comparisonOf(plan)} />
        </section>
      </div>

      <section className={card}>
        <h2 className="mb-1 text-sm font-semibold text-slate-800">Visit plan</h2>
        <p className="mb-3 text-xs text-slate-500">
          Edit the visit date, allocated amount or Skip; changes save automatically and the plan recalculates.
        </p>
        <PlanGrid rows={rows} onEdit={onEdit} />
      </section>
    </div>
  );
}
