const STYLES: Record<string, { label: string; cls: string }> = {
  cash_out_risk: { label: "Cash-out risk", cls: "bg-red-100 text-red-800 ring-red-300" },
  over_stocked: { label: "Over-stocked", cls: "bg-amber-100 text-amber-800 ring-amber-300" },
  ok: { label: "OK", cls: "bg-green-100 text-green-800 ring-green-300" },
  insufficient_history: { label: "Insufficient history", cls: "bg-slate-100 text-slate-700 ring-slate-300" },
  forecast_failed: { label: "Forecast failed", cls: "bg-slate-100 text-slate-700 ring-slate-300" },
};

/** Colour + always a text label (never colour alone). */
export function StatusBadge({ status }: { status: string }) {
  const s = STYLES[status] ?? { label: status, cls: "bg-slate-100 text-slate-700 ring-slate-300" };
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${s.cls}`}
    >
      {s.label}
    </span>
  );
}
