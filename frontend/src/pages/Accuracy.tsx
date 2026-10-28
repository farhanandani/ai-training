import { useMemo, useState } from "react";
import type { AccuracyAtm } from "../api/client";
import { useAccuracy, useFleet } from "../api/hooks";
import { Spinner } from "../components/Spinner";
import { BacktestChart } from "../components/charts/BacktestChart";
import { formatDate, formatRpCompact } from "../lib/format";

const pct = (v: number | null | undefined) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const BASELINE = "seasonal_naive";

const baselineWape = (a: AccuracyAtm) => a.candidates.find((c) => c.model === BASELINE)?.wape ?? null;

/** Chosen model beats the baseline when its WAPE is lower; the baseline itself shows a dash. */
function beats(a: AccuracyAtm): boolean | null {
  const b = baselineWape(a);
  const w = a.metrics?.wape;
  if (b == null || w == null || a.model === BASELINE) return null;
  return w < b;
}

const th = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500";
const td = "whitespace-nowrap px-3 py-2 text-sm tabular-nums";

export function AccuracyPage() {
  const acc = useAccuracy();
  const fleet = useFleet();
  const [sel, setSel] = useState<string | null>(null);
  const [originPick, setOriginPick] = useState<string>("");

  const atms = useMemo(() => acc.data?.atms ?? [], [acc.data]);
  const loc = useMemo(() => new Map((fleet.data?.atms ?? []).map((a) => [a.tid, a.location_name])), [fleet.data]);

  // default selection = first row
  const tid = sel && atms.some((a) => a.tid === sel) ? sel : (atms[0]?.tid ?? null);
  const atm = atms.find((a) => a.tid === tid);
  const origins = useMemo(() => [...new Set((atm?.backtest ?? []).map((p) => p.origin))].sort(), [atm]);
  const origin = origins.includes(originPick) ? originPick : (origins[origins.length - 1] ?? "");

  if (acc.isError) return <p role="alert" className="text-sm text-red-700">Could not load accuracy: {String(acc.error)}</p>;
  if (!acc.data) return <Spinner label="Loading accuracy" />;

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-slate-900">Forecast Accuracy</h2>
        <p className="text-sm text-slate-500">
          Rolling-origin backtest at horizon {acc.data.h} days. The baseline is a seasonal-naive forecast (same weekday last week).
        </p>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              {["TID", "Location", "Model", "WAPE", "MAPE", "MAE", "Coverage (p10-p90)", "Lebaran check WAPE", "Baseline WAPE", "Beats baseline"].map((h) => (
                <th key={h} className={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {atms.map((a) => {
              const b = beats(a);
              return (
                <tr
                  key={a.tid}
                  onClick={() => setSel(a.tid)}
                  className={`cursor-pointer hover:bg-slate-50 ${a.tid === tid ? "bg-blue-50" : ""}`}
                  aria-selected={a.tid === tid}
                >
                  <td className={`${td} font-medium`}>
                    <button type="button" className="text-left" onClick={() => setSel(a.tid)}>{a.tid}</button>
                  </td>
                  <td className={td}>{loc.get(a.tid) ?? "-"}</td>
                  <td className={td}>
                    {a.model ?? <span className="text-slate-500">{a.status.replace("_", " ")}</span>}
                    {a.backtest_stale && (
                      <span
                        title="Backtest from before the last data edit"
                        className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-inset ring-amber-300"
                      >
                        stale
                      </span>
                    )}
                  </td>
                  <td className={td}>{pct(a.metrics?.wape)}</td>
                  <td className={td}>{pct(a.metrics?.mape)}</td>
                  <td className={td}>{a.metrics?.mae == null ? "-" : formatRpCompact(a.metrics.mae)}</td>
                  <td className={td}>{pct(a.metrics?.coverage)}</td>
                  <td className={td}>{pct(a.lebaran_check?.metrics?.wape)}</td>
                  <td className={td}>{pct(baselineWape(a))}</td>
                  <td className={td}>
                    {b === null ? (
                      <span className="text-slate-400">-</span>
                    ) : b ? (
                      <span className="font-medium text-green-700" aria-label="Beats baseline">✓</span>
                    ) : (
                      <span className="font-medium text-red-700" aria-label="Does not beat baseline">✗</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {atm && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-sm font-semibold text-slate-800">
              Backtest: {atm.tid}
              {loc.get(atm.tid) ? ` (${loc.get(atm.tid)})` : ""}
            </h3>
            <label className="ml-auto flex items-center gap-1.5 text-sm">
              <span className="text-slate-500">Origin</span>
              <select
                aria-label="Backtest origin"
                className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                value={origin}
                onChange={(e) => setOriginPick(e.target.value)}
                disabled={origins.length === 0}
              >
                {origins.map((o) => (
                  <option key={o} value={o}>{formatDate(o)}</option>
                ))}
              </select>
            </label>
          </div>
          {origins.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">No backtest available for this ATM ({atm.error ?? atm.status.replace("_", " ")}).</p>
          ) : (
            <BacktestChart points={atm.backtest} origin={origin} />
          )}
        </div>
      )}
    </section>
  );
}
