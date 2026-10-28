import { useState } from "react";
import { ApiRequestError, type IssueDto, type WriteResponse } from "../api/client";
import { useUploadData } from "../api/hooks";
import { ValidationPanel } from "./ValidationPanel";

type Kind = "log" | "master" | "holidays";
const btn =
  "rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50";

/** Upload a CSV/XLSX (kind + replace|merge). 413 / 422 errors are shown inline with their issues; success goes to onDone. */
export function UploadDialog({ onClose, onDone }: { onClose: () => void; onDone: (r: WriteResponse) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<Kind>("log");
  const [mode, setMode] = useState<"replace" | "merge">("merge");
  const [error, setError] = useState<{ message: string; issues: IssueDto[] } | null>(null);
  const upload = useUploadData();

  const submit = () => {
    if (!file) return;
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    fd.append("mode", mode);
    upload.mutate(fd, {
      onSuccess: (r) => {
        onDone(r as WriteResponse);
        onClose();
      },
      onError: (e) => {
        if (e instanceof ApiRequestError) {
          const issues = ((e.details as { issues?: IssueDto[] } | undefined)?.issues ?? []) as IssueDto[];
          setError({
            message: e.code === "FILE_TOO_LARGE" ? `File too large: ${e.message}` : `${e.code}: ${e.message}`,
            issues,
          });
        } else setError({ message: String(e), issues: [] });
      },
    });
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/30 p-4">
      <div
        role="dialog"
        aria-label="Upload data"
        className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-lg bg-white p-5 shadow-xl"
      >
        <h2 className="text-base font-semibold text-slate-900">Upload data</h2>
        <div className="mt-3 grid gap-3 text-sm">
          <label className="grid gap-1">
            <span className="text-slate-600">File (CSV or Excel)</span>
            <input
              type="file"
              aria-label="File"
              accept=".csv,.xlsx,.xls"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="w-12 text-slate-600">Kind</span>
            <select
              aria-label="Kind"
              className="rounded border border-slate-300 px-2 py-1"
              value={kind}
              onChange={(e) => setKind(e.target.value as Kind)}
            >
              <option value="log">Daily log</option>
              <option value="master">ATM master</option>
              <option value="holidays">Holidays</option>
            </select>
          </label>
          <fieldset className="flex items-center gap-4">
            <legend className="sr-only">Mode</legend>
            <span className="w-12 text-slate-600">Mode</span>
            <label className="flex items-center gap-1">
              <input type="radio" name="upload-mode" checked={mode === "merge"} onChange={() => setMode("merge")} />{" "}
              Merge
            </label>
            <label className="flex items-center gap-1">
              <input type="radio" name="upload-mode" checked={mode === "replace"} onChange={() => setMode("replace")} />{" "}
              Replace
            </label>
          </fieldset>
        </div>
        {error && (
          <div role="alert" className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <p className="font-medium">{error.message}</p>
            {error.issues.length > 0 && (
              <div className="mt-2 text-slate-800">
                <ValidationPanel issues={error.issues} title="Issues found in the file" />
              </div>
            )}
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className={btn} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={!file || upload.isPending}
            onClick={submit}
          >
            {upload.isPending ? "Uploading..." : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
