const FILL: Record<string, string> = {
  cash_out_risk: "bg-red-500",
  over_stocked: "bg-amber-500",
  ok: "bg-green-500",
};

/** Balance vs capacity bar; colour follows the status (same palette as StatusBadge). */
export function BalanceGauge({
  balance,
  capacity,
  status,
}: {
  balance: number;
  capacity: number;
  status?: string;
}) {
  const pct = capacity > 0 ? Math.max(0, Math.min(100, (balance / capacity) * 100)) : 0;
  return (
    <div className="flex items-center gap-2" title={`${pct.toFixed(0)}% of capacity`}>
      <div
        className="h-2 w-24 overflow-hidden rounded-full bg-slate-200"
        role="meter"
        aria-label="Balance vs capacity"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
      >
        <div
          className={`h-full rounded-full ${FILL[status ?? ""] ?? "bg-slate-400"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-slate-500">{pct.toFixed(0)}%</span>
    </div>
  );
}
