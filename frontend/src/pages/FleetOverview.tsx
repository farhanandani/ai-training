import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { FleetAtm } from "../api/client";
import { useFleet } from "../api/hooks";
import { BalanceGauge } from "../components/BalanceGauge";
import { KpiTile } from "../components/KpiTile";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { formatDate, formatRp, formatRpCompact } from "../lib/format";

const SEVERITY: Record<string, number> = {
  cash_out_risk: 0,
  over_stocked: 1,
  ok: 2,
  insufficient_history: 3,
  forecast_failed: 3,
};
const sev = (s: string) => SEVERITY[s] ?? 3;
const typeLabel = (t: string) => t.replace(/_/g, " ");

type SortKey = "default" | "location" | "status" | "balance" | "days" | "next_visit" | "amount";
type SortState = { key: SortKey; dir: 1 | -1 };

// null sorts last in both directions
function cmpNullable<T>(a: T | null, b: T | null, dir: 1 | -1, cmp: (x: T, y: T) => number) {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return dir * cmp(a, b);
}
const num = (x: number, y: number) => x - y;
const str = (x: string, y: string) => x.localeCompare(y);

function sortAtms(atms: FleetAtm[], { key, dir }: SortState): FleetAtm[] {
  const byDays = (a: FleetAtm, b: FleetAtm) => cmpNullable(a.days_of_cash, b.days_of_cash, 1, num);
  const out = [...atms];
  out.sort((a, b) => {
    switch (key) {
      case "location":
        return dir * str(a.location_name, b.location_name);
      case "status":
        return dir * (sev(a.status) - sev(b.status)) || byDays(a, b);
      case "balance":
        return dir * (a.balance - b.balance);
      case "days":
        return cmpNullable(a.days_of_cash, b.days_of_cash, dir, num);
      case "next_visit":
        return cmpNullable(a.next_visit, b.next_visit, dir, str);
      case "amount":
        return cmpNullable(a.recommended_amount, b.recommended_amount, dir, num);
      default:
        // severity first, then days of cash ascending
        return sev(a.status) - sev(b.status) || byDays(a, b) || str(a.tid, b.tid);
    }
  });
  return out;
}

function Th({
  label,
  k,
  sort,
  setSort,
  align = "left",
}: {
  label: string;
  k: SortKey;
  sort: SortState;
  setSort: (s: SortState) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === k;
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
      className={`px-3 py-2 font-medium ${align === "right" ? "text-right" : "text-left"}`}
    >
      <button
        type="button"
        className={`inline-flex items-center gap-1 hover:text-slate-900 ${active ? "text-slate-900" : ""}`}
        onClick={() => setSort({ key: k, dir: active && sort.dir === 1 ? -1 : 1 })}
      >
        {label}
        <span aria-hidden className="w-2 text-[10px]">
          {active ? (sort.dir === 1 ? "▲" : "▼") : ""}
        </span>
      </button>
    </th>
  );
}

function SkeletonRow({ tid }: { tid: string }) {
  return (
    <tr className="border-t border-slate-100" aria-label={`Forecasting ${tid}`}>
      <td className="px-3 py-3">
        <div className="h-3 w-40 animate-pulse rounded bg-slate-200" />
        <div className="mt-1.5 h-2.5 w-24 animate-pulse rounded bg-slate-100" />
      </td>
      {Array.from({ length: 6 }, (_, i) => (
        <td key={i} className="px-3 py-3">
          <div className="h-3 w-full max-w-24 animate-pulse rounded bg-slate-100" />
        </td>
      ))}
    </tr>
  );
}

export function FleetPage() {
  const { data, isLoading, error } = useFleet();
  const [sort, setSort] = useState<SortState>({ key: "default", dir: 1 });
  const rows = useMemo(() => sortAtms(data?.atms ?? [], sort), [data?.atms, sort]);

  if (error)
    return (
      <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        Could not load the fleet: {error.message}
      </div>
    );
  if (isLoading || !data) return <Spinner label="Loading fleet" />;

  const ready = new Set(data.atms.map((a) => a.tid));
  const pending = data.pending_tids.filter((t) => !ready.has(t));
  const k = data.kpis;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiTile
          label="ATMs at cash-out risk"
          value={k.at_risk}
          tone={k.at_risk ? "red" : "green"}
          // hint="p90 balance falls below the safe minimum before the next visit"
          // hint="p90 balance falls below the safe minimum within the horizon"
          hint="Below safe minimum soon, or projected to run out within the horizon"
        />
        <KpiTile
          label="Over-stocked ATMs"
          value={k.over_stocked}
          tone={k.over_stocked ? "amber" : "green"}
          hint="Too much idle cash at the next visit"
        />
        <KpiTile
          label="Idle cash"
          value={formatRpCompact(k.idle_cash)}
          hint="Average above the safe minimum over the horizon"
        />
        <KpiTile
          label="Recommended refill"
          value={formatRpCompact(k.recommended_total)}
          hint={`All visits in the next ${data.h} days`}
        />
      </div>

      <section className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="w-full min-w-[960px] text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <Th label="Location" k="location" sort={sort} setSort={setSort} />
              <Th label="Status" k="status" sort={sort} setSort={setSort} />
              <Th label="Balance" k="balance" sort={sort} setSort={setSort} />
              <Th label="Days of cash" k="days" sort={sort} setSort={setSort} align="right" />
              <Th label="Next visit" k="next_visit" sort={sort} setSort={setSort} />
              <Th label="Recommended refill" k="amount" sort={sort} setSort={setSort} align="right" />
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.tid} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-3 py-3">
                  <div className="font-medium text-slate-900">{a.location_name}</div>
                  <div className="text-xs text-slate-500">
                    {a.tid} · <span className="capitalize">{typeLabel(a.location_type)}</span>
                    {a.inferred_master && (
                      <span className="ml-2 rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-800 ring-1 ring-inset ring-sky-300">
                        Inferred master - review
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-3">
                  <StatusBadge status={a.status} />
                </td>
                <td className="px-3 py-3">
                  <div className="tabular-nums text-slate-900">{formatRp(a.balance)}</div>
                  <BalanceGauge balance={a.balance} capacity={a.capacity} status={a.status} />
                </td>
                <td className="px-3 py-3 text-right tabular-nums">
                  {a.days_of_cash != null ? `${a.days_of_cash} d` : "-"}
                </td>
                <td className="px-3 py-3 tabular-nums">{a.next_visit ? formatDate(a.next_visit) : "-"}</td>
                <td className="px-3 py-3 text-right tabular-nums">
                  {a.recommended_amount != null ? formatRp(a.recommended_amount) : "-"}
                </td>
                <td className="px-3 py-3 text-right">
                  <Link
                    to={{ pathname: `/atm/${encodeURIComponent(a.tid)}`, search: window.location.search }}
                    className="whitespace-nowrap text-blue-700 hover:underline"
                  >
                    Details &rarr;
                  </Link>
                </td>
              </tr>
            ))}
            {pending.map((t) => (
              <SkeletonRow key={t} tid={t} />
            ))}
          </tbody>
        </table>
        {pending.length > 0 && (
          <div className="border-t border-slate-100 px-3 py-2">
            <Spinner label={`Forecasting ${pending.length} more ATM${pending.length === 1 ? "" : "s"}...`} />
          </div>
        )}
      </section>
    </div>
  );
}
