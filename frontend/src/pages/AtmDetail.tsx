import { Link, useParams } from "react-router-dom";
import { useAtm } from "../api/hooks";
import { BalanceGauge } from "../components/BalanceGauge";
import { BalanceChart } from "../components/charts/BalanceChart";
import { DemandForecastChart } from "../components/charts/DemandForecastChart";
import { RecommendationCard } from "../components/RecommendationCard";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { formatRp } from "../lib/format";

const typeLabel = (t: string) => t.replace(/_/g, " ");

export function AtmDetailPage() {
  const { tid } = useParams();
  const { data: atm, isLoading, error } = useAtm(tid);
  const back = (
    <Link
      to={{ pathname: "/", search: window.location.search }}
      className="text-sm text-blue-700 hover:underline"
    >
      &larr; Fleet overview
    </Link>
  );

  if (error)
    return (
      <div className="space-y-3">
        {back}
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Could not load {tid}: {error.message}
        </div>
      </div>
    );
  if (isLoading || !atm)
    return (
      <div className="space-y-3">
        {back}
        <Spinner label="Loading ATM" />
      </div>
    );

  const m = atm.master;
  const last = atm.history[atm.history.length - 1];
  const hasForecast = atm.forecast.length > 0;

  return (
    <div className="space-y-5">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">{m.location_name}</h2>
          <p className="text-sm text-slate-500">
            {atm.tid} · <span className="capitalize">{typeLabel(m.location_type)}</span> · capacity{" "}
            {formatRp(m.capacity)} · safe minimum {formatRp(m.min_safe_balance)} · refill every{" "}
            {m.replenish_cycle_days} days
          </p>
        </div>
        <div className="flex items-center gap-3">
          {m.inferred && (
            <span className="rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-medium text-sky-800 ring-1 ring-inset ring-sky-300">
              Inferred master - review
            </span>
          )}
          <StatusBadge status={atm.status} />
          <span className="text-sm text-slate-700">
            {atm.days_of_cash != null
              ? `${atm.days_of_cash} day${atm.days_of_cash === 1 ? "" : "s"} of cash`
              : ""}
          </span>
          {last && <BalanceGauge balance={last.closing_balance} capacity={m.capacity} status={atm.status} />}
        </div>
      </div>

      {atm.model?.fallback && (
        <div
          role="note"
          className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          Fallback forecast: this ATM has too little or irregular history for the full model, so a simple
          seasonal-average forecast is used. Treat the band as indicative.
        </div>
      )}
      {atm.error && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {atm.error}
        </div>
      )}
      {atm.pending && <Spinner label="Forecast is being computed..." />}

      {hasForecast && (
        <div className="grid gap-5 xl:grid-cols-3">
          <div className="min-w-0 space-y-5 xl:col-span-2">
            <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-800">Daily withdrawal: history and forecast</h3>
              <DemandForecastChart atm={atm} />
            </section>
            <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-800">
                Cash balance: current policy vs recommended plan
              </h3>
              <BalanceChart atm={atm} />
            </section>
          </div>
          <RecommendationCard atm={atm} />
        </div>
      )}
    </div>
  );
}
