import { useEffect } from "react";
import { NavLink } from "react-router-dom";
import { useAppContext, useFleet, useJobStatus } from "../api/hooks";
import { H_MAX, H_MIN, SLS, useControls } from "../state/controls";
import type { SL } from "../api/client";
import { Spinner } from "./Spinner";

const NAV = [
  { to: "/", label: "Fleet", end: true },
  { to: "/planner", label: "Planner" },
  { to: "/data", label: "Data" },
  { to: "/accuracy", label: "Accuracy" },
];

export function Header() {
  const { data: ctx, isError } = useAppContext();
  const { scenario, asOf, h, sl, setContext, setScenario, setAsOf, setH, setSl } = useControls();
  const noData = !!ctx && !ctx.as_of_max; // F5: no daily log loaded

  // apply scenario/URL once the context arrives (and re-clamp if the data range changes)
  useEffect(() => {
    if (ctx) setContext(ctx);
  }, [ctx, setContext]);

  // recompute progress: the fleet read reports the job running for the current view
  const fleet = useFleet();
  const jobId = fleet.data?.pending_tids?.length ? fleet.data.job_id : null;
  const job = useJobStatus(jobId);
  const forecasting = !!jobId && !job.data?.done;

  const field = "rounded border border-slate-300 bg-white px-2 py-1 text-sm";
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3">
        <h1 className="text-lg font-semibold text-slate-900">ATM Cash Forecasting</h1>
        <nav className="flex gap-1" aria-label="Main">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={{ pathname: n.to, search: window.location.search }}
              end={n.end}
              className={({ isActive }) =>
                `rounded px-3 py-1 text-sm ${isActive ? "bg-blue-600 text-white" : "text-slate-700 hover:bg-slate-100"}`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-1.5">
            <span className="text-slate-500">Scenario</span>
            <select
              aria-label="Scenario"
              className={field}
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
              // disabled={!ctx}
              disabled={!ctx || noData}
            >
              {noData && <option value="">No data</option>}
              {ctx?.scenarios.map((s) => (
                // <option key={s.id} value={s.id}>
                <option
                  key={s.id}
                  value={s.id}
                  disabled={!s.in_range}
                  title={s.in_range ? undefined : "Outside the loaded data's date range"}
                >
                  {s.label}
                </option>
              ))}
              {scenario === "custom" && <option value="custom">Custom</option>}
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            <span className="text-slate-500">As-of</span>
            <input
              aria-label="As-of date"
              type="date"
              className={field}
              value={asOf}
              // min={ctx?.as_of_min}
              // max={ctx?.as_of_max}
              min={ctx?.as_of_min ?? undefined}
              max={ctx?.as_of_max ?? undefined}
              onChange={(e) => e.target.value && setAsOf(e.target.value)}
              // disabled={!ctx}
              disabled={!ctx || noData}
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span className="text-slate-500">Horizon</span>
            <input
              aria-label="Horizon (days)"
              type="range"
              min={H_MIN}
              max={H_MAX}
              value={h}
              onChange={(e) => setH(Number(e.target.value))}
            />
            <span className="w-12 tabular-nums">{h} d</span>
          </label>
          <label className="flex items-center gap-1.5">
            <span className="text-slate-500">Service level</span>
            <select
              aria-label="Service level"
              className={field}
              value={sl}
              onChange={(e) => setSl(e.target.value as SL)}
            >
              {SLS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <span
            className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700"
            title="Data source"
          >
            {/* {ctx ? ctx.data_source : isError ? "API unreachable" : "..."} */}
            {ctx ? (noData ? "No data loaded" : ctx.data_source) : isError ? "API unreachable" : "..."}
          </span>
          {forecasting && (
            <Spinner label={`Forecasting ${job.data?.finished ?? 0}/${job.data?.total ?? "?"}`} />
          )}
        </div>
      </div>
    </header>
  );
}
