import type { Comparison, PolicyStats } from "./planRows";
import { formatRp } from "../lib/format";

type Row = { label: string; get: (s: PolicyStats) => number; fmt: (n: number) => string; neutral?: boolean };
const int = (n: number) => String(n);
const ROWS: Row[] = [
  { label: "Cash-out days", get: (s) => s.cash_out_days, fmt: int },
  { label: "Avg idle cash", get: (s) => s.idle_cash, fmt: formatRp },
  { label: "Idle cash cost", get: (s) => s.idle_cost, fmt: formatRp },
  { label: "Visits", get: (s) => s.visits, fmt: int },
  { label: "Visit cost", get: (s) => s.visit_cost, fmt: formatRp },
  { label: "Cash loaded", get: (s) => s.loaded, fmt: formatRp, neutral: true },
];

function delta(row: Row, cur: PolicyStats, rec: PolicyStats) {
  const d = row.get(rec) - row.get(cur);
  if (d === 0) return { text: "0", cls: "text-slate-500" };
  // every metric here is a cost or a count to minimise: lower is better
  return {
    text: `${d > 0 ? "+" : "-"}${row.fmt(Math.abs(d)).replace(/^-/, "")}`,
    // cls: d < 0 ? "text-green-700" : "text-red-700",
    cls: row.neutral ? "text-slate-500" : d < 0 ? "text-green-700" : "text-red-700",
  };
}

function Table({ cur, rec }: { cur: PolicyStats; rec: PolicyStats }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th className="py-1.5 text-left font-medium" />
          <th className="py-1.5 text-right font-medium">Current policy</th>
          <th className="py-1.5 text-right font-medium">Recommended</th>
          <th className="py-1.5 text-right font-medium">&Delta;</th>
        </tr>
      </thead>
      <tbody>
        {ROWS.map((r) => {
          const d = delta(r, cur, rec);
          return (
            <tr key={r.label} className="border-t border-slate-100">
              <td className="py-1.5 text-slate-700">{r.label}</td>
              <td className="py-1.5 text-right tabular-nums">{r.fmt(r.get(cur))}</td>
              <td className="py-1.5 text-right tabular-nums font-medium text-slate-900">{r.fmt(r.get(rec))}</td>
              <td className={`py-1.5 text-right tabular-nums ${d.cls}`}>{d.text}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ComparisonPanel({ comparison }: { comparison: Comparison }) {
  const rp = comparison.replay;
  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-1 text-sm font-semibold text-slate-800">On forecast demand</h3>
        <Table cur={comparison.current} rec={comparison.recommended} />
      </div>
      {rp && (
        <div className="border-t border-slate-200 pt-4">
          <h3 className="text-sm font-semibold text-slate-800">Replay against actual demand</h3>
          <p className="mb-1 text-xs text-slate-500">
            Basis: {rp.basis === "true_demand" ? "Actual (true demand)" : "Estimated"}
          </p>
          <Table cur={rp.current} rec={rp.recommended} />
        </div>
      )}
    </div>
  );
}
