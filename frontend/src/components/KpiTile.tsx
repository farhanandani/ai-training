import type { ReactNode } from "react";

const BAR = { red: "border-l-red-500", amber: "border-l-amber-500", green: "border-l-green-500" };

export function KpiTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "red" | "amber" | "green";
}) {
  return (
    <div
      className={`rounded-lg border border-slate-200 border-l-4 bg-white p-4 shadow-sm ${tone ? BAR[tone] : "border-l-slate-300"}`}
    >
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}
