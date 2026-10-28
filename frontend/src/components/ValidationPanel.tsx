import { useMemo, useState } from "react";
import type { IssueDto } from "../api/client";

const MAX_ROWS = 50;
const GROUPS: { sev: IssueDto["severity"]; title: string; cls: string }[] = [
  { sev: "error", title: "Errors", cls: "text-red-800 bg-red-50 border-red-200" },
  { sev: "warning", title: "Warnings", cls: "text-amber-800 bg-amber-50 border-amber-200" },
  { sev: "info", title: "Info", cls: "text-slate-700 bg-slate-50 border-slate-200" },
];

/** Issues grouped error -> warning -> info, counts in the header, first 50 rows per group, TID filter. */
export function ValidationPanel({ issues, title = "Data validation" }: { issues: IssueDto[]; title?: string }) {
  const [tid, setTid] = useState("");
  const tids = useMemo(() => [...new Set(issues.map((i) => i.tid).filter((t): t is string => !!t))].sort(), [issues]);
  const shown = tid ? issues.filter((i) => i.tid === tid) : issues;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
        <label className="ml-auto flex items-center gap-1.5 text-sm">
          <span className="text-slate-500">TID</span>
          <input
            aria-label="Filter by TID"
            list="validation-tids"
            className="rounded border border-slate-300 px-2 py-1 text-sm"
            placeholder="All"
            value={tid}
            onChange={(e) => setTid(e.target.value)}
          />
          <datalist id="validation-tids">
            {tids.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </label>
      </div>
      {issues.length === 0 && <p className="mt-2 text-sm text-slate-500">No validation issues.</p>}
      {GROUPS.map((g) => {
        const rows = shown.filter((i) => i.severity === g.sev);
        if (rows.length === 0) return null;
        return (
          <section key={g.sev} className="mt-3">
            <h3 className={`rounded border px-2 py-1 text-sm font-medium ${g.cls}`}>
              {g.title} ({rows.length})
            </h3>
            <ul className="mt-1 divide-y divide-slate-100 text-sm">
              {rows.slice(0, MAX_ROWS).map((i, k) => (
                <li key={k} className="flex flex-wrap gap-x-3 py-1">
                  <code className="text-xs text-slate-500">{i.code}</code>
                  <span className="text-slate-800">{i.message}</span>
                  {(i.tid || i.date) && <span className="text-xs text-slate-500">{[i.tid, i.date].filter(Boolean).join(" / ")}</span>}
                </li>
              ))}
            </ul>
            {rows.length > MAX_ROWS && (
              <p className="mt-1 text-xs text-slate-500">Showing the first {MAX_ROWS} of {rows.length}.</p>
            )}
          </section>
        );
      })}
    </div>
  );
}
