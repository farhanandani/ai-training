import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import type { CellValueChangedEvent, ColDef, ICellRendererParams } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { formatRp } from "../lib/format";
import type { PlanRow, RowEdit } from "./planRows";

const CHIP: Record<string, { label: string; cls: string }> = {
  underfunded: { label: "Underfunded", cls: "bg-red-100 text-red-800 ring-red-300" },
  capacity_shortfall: { label: "Capacity shortfall", cls: "bg-red-100 text-red-800 ring-red-300" },
  skip: { label: "Skip", cls: "bg-slate-100 text-slate-700 ring-slate-300" },
  merged: { label: "Merged", cls: "bg-blue-100 text-blue-800 ring-blue-300" },
  manual: { label: "Manual", cls: "bg-purple-100 text-purple-800 ring-purple-300" },
};

function Chips({ data }: ICellRendererParams<PlanRow>) {
  if (!data) return null;
  const flags = [...data.flags.filter((f) => f !== "skip" || data.skip)];
  if (data.skip && !flags.includes("skip")) flags.push("skip");
  if (data.manual) flags.push("manual");
  return (
    <span className="flex h-full flex-wrap items-center gap-1">
      {flags.map((f) => {
        const c = CHIP[f] ?? { label: f, cls: "bg-slate-100 text-slate-700 ring-slate-300" };
        return (
          <span key={f} className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${c.cls}`}>
            {c.label}
          </span>
        );
      })}
    </span>
  );
}

const KIND: Record<string, string> = { scheduled: "Scheduled", extra: "Extra", moved: "Moved" };
const ISO = /^\d{4}-\d{2}-\d{2}$/;

export function PlanGrid({ rows, onEdit }: { rows: PlanRow[]; onEdit: (key: string, e: RowEdit) => void }) {
  const cols = useMemo<ColDef<PlanRow>[]>(
    () => [
      { headerName: "ATM", field: "location", minWidth: 190, flex: 1.2, sort: "asc", sortIndex: 1 },
      {
        headerName: "Visit date",
        field: "date",
        editable: true,
        width: 130,
        sort: "asc",
        sortIndex: 0,
        // only a valid yyyy-mm-dd value is accepted
        valueSetter: (p) => {
          const v = String(p.newValue ?? "").trim();
          if (!ISO.test(v) || v === p.data.date) return false;
          p.data.date = v;
          return true;
        },
      },
      { headerName: "Kind", field: "kind", width: 110, valueFormatter: (p) => KIND[p.value] ?? p.value },
      {
        headerName: "Recommended",
        field: "recommended",
        width: 160,
        type: "rightAligned",
        valueFormatter: (p) => formatRp(p.value),
      },
      {
        headerName: "Allocated (editable)",
        field: "amount",
        editable: true,
        width: 175,
        type: "rightAligned",
        cellClass: "font-medium",
        valueFormatter: (p) => formatRp(p.value),
        valueParser: (p) => Number(String(p.newValue).replace(/\D/g, "")),
        valueSetter: (p) => {
          const n = Number(p.newValue);
          if (!Number.isFinite(n) || n < 0 || n === p.data.amount) return false;
          p.data.amount = n;
          return true;
        },
      },
      { headerName: "Skip", field: "skip", editable: true, width: 80, cellDataType: "boolean" },
      { headerName: "Reason", field: "reason", flex: 1.6, minWidth: 220, tooltipField: "reason" },
      { headerName: "Flags", colId: "flags", cellRenderer: Chips, flex: 1.2, minWidth: 200, autoHeight: true },
    ],
    [],
  );

  const onChange = (e: CellValueChangedEvent<PlanRow>) => {
    if (!e.data) return;
    const f = e.colDef.field;
    if (f === "amount") onEdit(e.data.key, { amount: e.data.amount });
    else if (f === "skip") onEdit(e.data.key, { skip: !!e.data.skip });
    else if (f === "date") onEdit(e.data.key, { date: e.data.date });
  };

  return (
    <div className="ag-theme-quartz" style={{ width: "100%" }}>
      <AgGridReact<PlanRow>
        rowData={rows}
        columnDefs={cols}
        getRowId={(p) => p.data.key}
        domLayout="autoHeight"
        onCellValueChanged={onChange}
        suppressMovableColumns
        animateRows={false}
      />
    </div>
  );
}
