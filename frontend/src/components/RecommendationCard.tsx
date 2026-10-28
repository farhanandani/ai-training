import type { AtmResponse } from "../api/client";
import { formatDate, formatRp } from "../lib/format";

const pct = (v: number | null | undefined) => (v == null ? "n/a" : `${(v * 100).toFixed(1)}%`);

export function RecommendationCard({ atm }: { atm: AtmResponse }) {
  const visits = atm.visits;
  const first = visits[0];
  const model = atm.model;
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Recommendation</h3>
      {first ? (
        <>
          <p className="mt-2 text-lg font-semibold text-slate-900">
            {first.amount > 0 ? (
              <>
                Refill {formatRp(first.amount)} on {formatDate(first.date)}
              </>
            ) : (
              <>Skip the visit on {formatDate(first.date)}</>
            )}
          </p>
          <p className="mt-1 text-sm text-slate-600">{first.reason}</p>
        </>
      ) : (
        <p className="mt-2 text-sm text-slate-600">No visit is needed within the horizon.</p>
      )}
      {visits.length > 1 && (
        <ul className="mt-4 divide-y divide-slate-100 text-sm">
          {visits.slice(1).map((v) => (
            <li key={v.date + v.kind} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span className="w-24 font-medium text-slate-800">{formatDate(v.date)}</span>
              <span
                className={`rounded px-1.5 py-0.5 text-xs ${v.kind === "extra" ? "bg-violet-100 text-violet-800" : "bg-slate-100 text-slate-700"}`}
              >
                {v.kind === "extra" ? "Extra" : v.kind === "scheduled" ? "Scheduled" : v.kind}
              </span>
              <span className="tabular-nums text-slate-900">{formatRp(v.amount)}</span>
              {v.reason && v.reason !== "Scheduled visit" && (
                <span className="text-slate-500">{v.reason}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-slate-100 pt-3 text-sm">
        <div>
          <dt className="text-xs text-slate-500">Model</dt>
          <dd className="font-medium text-slate-900">{model?.name ?? "n/a"}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Backtest WAPE</dt>
          <dd className="font-medium text-slate-900">{pct(atm.metrics?.wape)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Interval coverage</dt>
          <dd className="font-medium text-slate-900">{pct(atm.metrics?.coverage)}</dd>
        </div>
      </dl>
    </section>
  );
}
