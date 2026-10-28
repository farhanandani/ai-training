import { useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type { CellValueChangedEvent, ColDef } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import {
  ApiRequestError,
  type HolidayRow,
  type IssueDto,
  type LogRow,
  type MasterRow,
  type WriteResponse,
} from "../api/client";
import {
  useAppContext,
  useDataLog,
  useDeleteLog,
  useHolidayRows,
  useMasterRows,
  usePatchLog,
  usePostLog,
  usePutHolidays,
  usePutMaster,
  useResetData,
  useValidation,
} from "../api/hooks";
import { UploadDialog } from "../components/UploadDialog";
import { ValidationPanel } from "../components/ValidationPanel";
import { Spinner } from "../components/Spinner";

const card = "rounded-lg border border-slate-200 bg-white p-4 shadow-sm";
const btn =
  "rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50";
const primary =
  "rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50";
const input = "rounded border border-slate-300 bg-white px-2 py-1 text-sm";
const PAGE_SIZE = 200;
const ISO = /^\d{4}-\d{2}-\d{2}$/;
const NUM_FIELDS = ["opening_balance", "withdrawal", "replenishment", "closing_balance"] as const;
type Tab = "log" | "master" | "holidays";
type Cb = { onSuccess: (r: WriteResponse) => void; onError: (e: unknown) => void };

const keyOf = (r: { tid: string; date: string }) => `${r.tid}|${r.date}`;
const errText = (e: unknown) => (e instanceof ApiRequestError ? `${e.code}: ${e.message}` : String(e));
const int = (v: unknown) => Math.max(0, Math.round(Number(String(v).replace(/\D/g, "")) || 0));
const idNum = new Intl.NumberFormat("id-ID");

type Edit = Partial<LogRow> & { tid: string; date: string };

function LogTab({ onWrite }: { onWrite: (r: WriteResponse) => void }) {
  const { data: ctx } = useAppContext();
  const [tid, setTid] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [selected, setSelected] = useState<LogRow[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const blank = { tid: "", date: "", opening_balance: "", withdrawal: "", replenishment: "", closing_balance: "" };
  const [draft, setDraft] = useState<Record<string, string>>(blank);

  const log = useDataLog({ tid, from, to, page });
  const patch = usePatchLog();
  const post = usePostLog();
  const del = useDeleteLog();
  const total = log.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const rows = useMemo(
    () => (log.data?.rows ?? []).map((r) => ({ ...r, ...(edits[keyOf(r)] ?? {}) })),
    [log.data, edits],
  );
  const cols = useMemo<ColDef<LogRow>[]>(
    () => [
      { headerName: "TID", field: "tid", width: 190, checkboxSelection: true, headerCheckboxSelection: true },
      { headerName: "Date", field: "date", width: 130 },
      ...NUM_FIELDS.map<ColDef<LogRow>>((f) => ({
        headerName: f.replace("_", " ").replace(/^./, (c) => c.toUpperCase()),
        field: f,
        editable: true,
        type: "rightAligned",
        flex: 1,
        valueFormatter: (p) => (p.value == null ? "" : idNum.format(p.value)),
        valueParser: (p) => int(p.newValue),
      })),
      { headerName: "Source", field: "source", width: 110 },
    ],
    [],
  );

  const onChange = (e: CellValueChangedEvent<LogRow>) => {
    const f = e.colDef.field as (typeof NUM_FIELDS)[number] | undefined;
    if (!e.data || !f) return;
    const k = keyOf(e.data);
    const { tid: t, date: d } = e.data;
    setEdits((cur) => ({ ...cur, [k]: { ...cur[k], tid: t, date: d, [f]: e.data![f] } }));
  };

  const dirty = Object.keys(edits).length;
  const cb = (after?: () => void): Cb => ({
    onSuccess: (r) => {
      setMsg(null);
      after?.();
      onWrite(r);
    },
    onError: (e) => setMsg(errText(e)),
  });

  const save = () => patch.mutate({ rows: Object.values(edits) }, cb(() => setEdits({})) as never);
  const remove = () =>
    del.mutate({ keys: selected.map((r) => ({ tid: r.tid, date: r.date })) }, cb(() => setSelected([])) as never);
  const add = () => {
    if (!draft.tid.trim() || !ISO.test(draft.date)) return setMsg("Enter a TID and a date (yyyy-mm-dd).");
    post.mutate(
      {
        rows: [
          {
            tid: draft.tid.trim(),
            date: draft.date,
            opening_balance: int(draft.opening_balance),
            withdrawal: int(draft.withdrawal),
            replenishment: int(draft.replenishment),
            closing_balance: int(draft.closing_balance),
          },
        ],
      },
      cb(() => {
        setAdding(false);
        setDraft(blank);
      }) as never,
    );
  };

  return (
    <div className={card}>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="grid gap-0.5">
          <span className="text-slate-500">TID</span>
          <select
            aria-label="TID"
            className={input}
            value={tid}
            onChange={(e) => {
              setTid(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All ATMs</option>
            {ctx?.tids.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-0.5">
          <span className="text-slate-500">From</span>
          <input
            aria-label="From date"
            type="date"
            className={input}
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <label className="grid gap-0.5">
          <span className="text-slate-500">To</span>
          <input
            aria-label="To date"
            type="date"
            className={input}
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button type="button" className={btn} onClick={() => setAdding((a) => !a)}>
            Add row
          </button>
          <button type="button" className={btn} disabled={selected.length === 0 || del.isPending} onClick={remove}>
            Delete selected ({selected.length})
          </button>
          <button type="button" className={primary} disabled={dirty === 0 || patch.isPending} onClick={save}>
            Save changes{dirty ? ` (${dirty})` : ""}
          </button>
        </div>
      </div>
      {adding && (
        <div className="mt-3 flex flex-wrap items-end gap-2 rounded border border-slate-200 bg-slate-50 p-3 text-sm">
          {(Object.keys(blank) as (keyof typeof blank)[]).map((f) => (
            <label key={f} className="grid gap-0.5">
              <span className="text-slate-500">{f.replace("_", " ")}</span>
              <input
                aria-label={`New ${f}`}
                className={`${input} w-36`}
                type={f === "date" ? "date" : "text"}
                value={draft[f]}
                onChange={(e) => setDraft((d) => ({ ...d, [f]: e.target.value }))}
              />
            </label>
          ))}
          <button type="button" className={btn} disabled={post.isPending} onClick={add}>
            Add
          </button>
        </div>
      )}
      {msg && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {msg}
        </p>
      )}
      <div className="ag-theme-quartz mt-3" style={{ width: "100%" }}>
        <AgGridReact<LogRow>
          rowData={rows}
          columnDefs={cols}
          getRowId={(p) => keyOf(p.data)}
          domLayout="autoHeight"
          rowSelection="multiple"
          suppressRowClickSelection
          onSelectionChanged={(e) => setSelected(e.api.getSelectedRows())}
          onCellValueChanged={onChange}
          animateRows={false}
        />
      </div>
      <div className="mt-2 flex items-center gap-3 text-sm text-slate-600">
        <button type="button" className={btn} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          Previous
        </button>
        <span>
          Page {page} of {pages} ({total.toLocaleString("en-US")} rows)
        </span>
        <button type="button" className={btn} disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
          Next
        </button>
        {log.isFetching && <Spinner label="Loading" />}
      </div>
    </div>
  );
}

/** Small editable table for master / holidays: edit cells, add or delete rows, save the whole table (PUT). */
function TableTab<T extends object>({
  rows: serverRows,
  cols,
  blank,
  save,
  saving,
  onWrite,
}: {
  rows: T[];
  cols: ColDef<T>[];
  blank: T;
  save: (rows: T[], cb: Cb) => void;
  saving: boolean;
  onWrite: (r: WriteResponse) => void;
}) {
  const [local, setLocal] = useState<T[] | null>(null);
  const [selected, setSelected] = useState<T[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const rows = local ?? serverRows;
  return (
    <div className={card}>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btn} onClick={() => setLocal([...rows, { ...blank }])}>
          Add row
        </button>
        <button
          type="button"
          className={btn}
          disabled={selected.length === 0}
          onClick={() => setLocal(rows.filter((r) => !selected.includes(r)))}
        >
          Delete selected ({selected.length})
        </button>
        <button
          type="button"
          className={`ml-auto ${primary}`}
          disabled={local === null || saving}
          onClick={() =>
            save(local!, {
              onSuccess: (r) => {
                setMsg(null);
                setLocal(null);
                onWrite(r);
              },
              onError: (e) => setMsg(errText(e)),
            })
          }
        >
          Save changes
        </button>
      </div>
      {msg && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {msg}
        </p>
      )}
      <div className="ag-theme-quartz mt-3" style={{ width: "100%" }}>
        <AgGridReact<T>
          rowData={rows}
          columnDefs={cols}
          domLayout="autoHeight"
          rowSelection="multiple"
          suppressRowClickSelection
          onSelectionChanged={(e) => setSelected(e.api.getSelectedRows())}
          onCellValueChanged={() => setLocal([...rows])}
          animateRows={false}
        />
      </div>
    </div>
  );
}

const numCol = (field: keyof MasterRow, name: string): ColDef<MasterRow> => ({
  headerName: name,
  field,
  editable: true,
  type: "rightAligned",
  width: 150,
  valueParser: (p) => int(p.newValue),
});
const MASTER_COLS: ColDef<MasterRow>[] = [
  { headerName: "TID", field: "tid", editable: true, width: 140, checkboxSelection: true },
  { headerName: "Location", field: "location_name", editable: true, flex: 1, minWidth: 180 },
  { headerName: "Type", field: "location_type", editable: true, width: 120 },
  numCol("capacity", "Capacity"),
  numCol("min_safe_balance", "Min safe balance"),
  numCol("replenish_cycle_days", "Cycle (days)"),
  numCol("denomination", "Denomination"),
  numCol("cost_per_visit", "Cost per visit"),
  numCol("current_fill_level", "Current fill"),
  { headerName: "Next visit", field: "next_visit_date", editable: true, width: 130 },
];
const HOLIDAY_COLS: ColDef<HolidayRow>[] = [
  { headerName: "Date", field: "date", editable: true, width: 150, checkboxSelection: true },
  { headerName: "Name", field: "name", editable: true, flex: 1 },
  {
    headerName: "Type",
    field: "type",
    editable: true,
    width: 160,
    cellEditor: "agSelectCellEditor",
    cellEditorParams: { values: ["new_year", "christmas", "idul_fitri", "cuti_bersama", "national"] },
  },
];
const BLANK_MASTER: MasterRow = {
  tid: "",
  location_name: "",
  location_type: "",
  capacity: 0,
  min_safe_balance: 0,
  replenish_cycle_days: 7,
  denomination: 100000,
  cost_per_visit: 0,
  current_fill_level: 0,
  next_visit_date: null,
  inferred: false,
};

function MasterTab({ onWrite }: { onWrite: (r: WriteResponse) => void }) {
  const { data } = useMasterRows();
  const put = usePutMaster();
  return (
    <TableTab<MasterRow>
      rows={data?.rows ?? []}
      cols={MASTER_COLS}
      blank={BLANK_MASTER}
      saving={put.isPending}
      save={(rows, cb) => put.mutate({ rows }, cb as never)}
      onWrite={onWrite}
    />
  );
}

function HolidaysTab({ onWrite }: { onWrite: (r: WriteResponse) => void }) {
  const { data } = useHolidayRows();
  const put = usePutHolidays();
  return (
    <TableTab<HolidayRow>
      rows={data?.rows ?? []}
      cols={HOLIDAY_COLS}
      blank={{ date: "", name: "", type: "national" }}
      saving={put.isPending}
      save={(rows, cb) => put.mutate({ rows }, cb as never)}
      onWrite={onWrite}
    />
  );
}

export function DataEditorPage() {
  const [tab, setTab] = useState<Tab>("log");
  const [upload, setUpload] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [lastIssues, setLastIssues] = useState<IssueDto[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const validation = useValidation();
  const reset = useResetData();

  // issues returned by the last write win over the stored list until the next one; the header shows the
  // recompute job via the fleet read (pending_tids), which the write invalidates
  const onWrite = (r: WriteResponse) => {
    setLastIssues(r.issues);
    setNotice(null);
  };
  const issues = lastIssues ?? validation.data?.issues ?? [];

  const tabs: { id: Tab; label: string }[] = [
    { id: "log", label: "Daily Log" },
    { id: "master", label: "ATM Master" },
    { id: "holidays", label: "Holidays" },
  ];
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-slate-900">Data Editor</h2>
        <p className="text-sm text-slate-500">Edits recompute the forecasts automatically.</p>
        <div className="ml-auto flex flex-wrap gap-2">
          <button type="button" className={btn} onClick={() => setUpload(true)}>
            Upload
          </button>
          <a className={btn} href={`/api/data/download?kind=${tab}`} download>
            Download {tabs.find((t) => t.id === tab)?.label}
          </a>
          <button type="button" className={btn} onClick={() => setConfirmReset(true)}>
            Reset to dummy data
          </button>
        </div>
      </div>
      {notice && (
        <p role="status" className="rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          {notice}
        </p>
      )}
      <div role="tablist" className="flex gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${tab === t.id ? "border-blue-600 font-medium text-blue-700" : "border-transparent text-slate-600 hover:text-slate-900"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "log" && <LogTab onWrite={onWrite} />}
      {tab === "master" && <MasterTab onWrite={onWrite} />}
      {tab === "holidays" && <HolidaysTab onWrite={onWrite} />}
      <ValidationPanel issues={issues} />
      {upload && (
        <UploadDialog
          onClose={() => setUpload(false)}
          onDone={(r) => {
            onWrite(r);
            setNotice(
              `Upload accepted (${r.issues.length} issue${r.issues.length === 1 ? "" : "s"}). Forecasts are recomputing.`,
            );
          }}
        />
      )}
      {confirmReset && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/30 p-4">
          <div role="dialog" aria-label="Confirm reset" className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
            <p className="text-sm text-slate-800">
              Reset all data to the dummy dataset? Uploaded data and edits will be lost.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className={btn} onClick={() => setConfirmReset(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="rounded bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700 disabled:opacity-50"
                disabled={reset.isPending}
                onClick={() =>
                  reset.mutate(undefined, {
                    onSuccess: (r) => {
                      setLastIssues(null);
                      setNotice("Data reset to the dummy dataset.");
                      void r;
                      setConfirmReset(false);
                    },
                  })
                }
              >
                Reset
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
