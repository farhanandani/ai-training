// import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, qs } from "./client";
import type {
  AccuracyResponse,
  AtmResponse,
  ContextResponse,
  FleetResponse,
  HolidayRow,
  IssueDto,
  LogPage,
  LogRow,
  MasterRow,
  OverridesRequest,
  PlanResponse,
  SettingsResponse,
  SettingsUpdate,
  StatusResponse,
  WriteResponse,
} from "./client";
import { useControls } from "../state/controls";

/** App context (scenarios, bounds, dataset_version). Named useAppContext to avoid shadowing React.useContext. */
export function useAppContext() {
  return useQuery({
    queryKey: ["context"],
    queryFn: () => api<ContextResponse>("/api/context"),
    staleTime: 60_000,
  });
}

/** Current view params + dataset_version; query keys include them (ARCHITECTURE 9). Disabled until the context loaded. */
function useView() {
  const { asOf, h, sl } = useControls();
  const { data } = useAppContext();
  return { asOf, h, sl, v: data?.dataset_version ?? 0, ready: !!data && asOf !== "" };
}

export function useFleet() {
  const { asOf, h, sl, v, ready } = useView();
  return useQuery({
    queryKey: ["fleet", asOf, h, sl, v],
    queryFn: () => api<FleetResponse>(`/api/fleet${qs({ as_of: asOf, h, sl })}`),
    enabled: ready,
  });
}

export function useAtm(tid: string | undefined) {
  const { asOf, h, sl, v, ready } = useView();
  return useQuery({
    queryKey: ["atm", tid, asOf, h, sl, v],
    queryFn: () => api<AtmResponse>(`/api/atm/${encodeURIComponent(tid!)}${qs({ as_of: asOf, h, sl })}`),
    enabled: ready && !!tid,
  });
}

// export function usePlan(budget: number | null) {
/** persist=false: a reference query (the planner's unconstrained base) that must not overwrite saved settings */
export function usePlan(budget: number | null, persist = true) {
  const { asOf, h, sl, v, ready } = useView();
  return useQuery({
    // queryKey: ["plan", asOf, h, sl, budget, v],
    queryKey: ["plan", asOf, h, sl, budget, v, persist],
    queryFn: () =>
      api<PlanResponse>("/api/plan", {
        method: "POST",
        // body: JSON.stringify({ as_of: asOf, h, sl, budget }),
        body: JSON.stringify({ as_of: asOf, h, sl, budget, persist }),
      }),
    enabled: ready,
    // keep the previous plan on screen while a new budget / override version loads
    placeholderData: keepPreviousData,
  });
}

export function useAccuracy() {
  const { asOf, h, v, ready } = useView();
  return useQuery({
    queryKey: ["accuracy", asOf, h, v],
    queryFn: () => api<AccuracyResponse>(`/api/accuracy${qs({ as_of: asOf, h })}`),
    enabled: ready,
  });
}

/** Polls every 500 ms until the job is done; when it finishes, the read views refetch. */
export function useJobStatus(jobId: string | null | undefined) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["status", jobId],
    queryFn: async () => {
      const st = await api<StatusResponse>(`/api/status${qs({ job_id: jobId })}`);
      if (st.done) refreshViews(qc);
      return st;
    },
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.done ? false : 500),
  });
}

function refreshViews(qc: QueryClient) {
  // for (const k of ["fleet", "atm", "plan", "accuracy"]) void qc.invalidateQueries({ queryKey: [k] });
  // for (const k of ["fleet", "atm", "plan", "accuracy", "settings"]) void qc.invalidateQueries({ queryKey: [k] });
  for (const k of ["fleet", "atm", "plan", "accuracy", "settings", "datalog", "validation", "datamaster", "dataholidays"])
    void qc.invalidateQueries({ queryKey: [k] });
}

/** Write helper: after any write the dataset_version may have changed, so refetch the context and every view. */
export function useApiMutation<TBody, TOut = unknown>(method: string, path: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: TBody) =>
      api<TOut>(path, {
        method,
        body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["context"] });
      refreshViews(qc);
    },
  });
}

export const useResetData = () => useApiMutation<undefined>("POST", "/api/data/reset");
/** FormData must carry file, kind (log|master|holidays) and mode (replace|merge). */
export const useUploadData = () => useApiMutation<FormData>("POST", "/api/data/upload");
export const useSaveOverrides = () => useApiMutation<OverridesRequest>("PUT", "/api/plan/overrides");
export const useClearOverrides = () => useApiMutation<undefined>("DELETE", "/api/plan/overrides");

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResponse>("/api/settings") });
}
/** Light-layer settings (overstock threshold, idle rate): saved, then every view refetches. */
export const useSaveSettings = () => useApiMutation<SettingsUpdate, SettingsResponse>("PUT", "/api/settings");

// ---- Data editor (Task 19)
export interface LogQuery {
  tid: string;
  from: string;
  to: string;
  page: number;
}
export function useDataLog(q: LogQuery) {
  const { data: ctx } = useAppContext();
  return useQuery({
    queryKey: ["datalog", q, ctx?.dataset_version ?? 0],
    queryFn: () =>
      api<LogPage>(`/api/data/log${qs({ tid: q.tid, from: q.from, to: q.to, page: q.page, page_size: 200 })}`),
    placeholderData: keepPreviousData,
  });
}
export function useValidation() {
  const { data: ctx } = useAppContext();
  return useQuery({
    queryKey: ["validation", ctx?.dataset_version ?? 0],
    queryFn: () => api<{ issues: IssueDto[] }>("/api/data/validation"),
  });
}
export function useMasterRows() {
  const { data: ctx } = useAppContext();
  return useQuery({
    queryKey: ["datamaster", ctx?.dataset_version ?? 0],
    queryFn: () => api<{ rows: MasterRow[] }>("/api/data/master"),
  });
}
export function useHolidayRows() {
  const { data: ctx } = useAppContext();
  return useQuery({
    queryKey: ["dataholidays", ctx?.dataset_version ?? 0],
    queryFn: () => api<{ rows: HolidayRow[] }>("/api/data/holidays"),
  });
}
export const usePatchLog = () =>
  useApiMutation<{ rows: Partial<LogRow>[] }, WriteResponse>("PATCH", "/api/data/log");
export const usePostLog = () => useApiMutation<{ rows: Partial<LogRow>[] }, WriteResponse>("POST", "/api/data/log");
export const useDeleteLog = () =>
  useApiMutation<{ keys: { tid: string; date: string }[] }, WriteResponse>("DELETE", "/api/data/log");
export const usePutMaster = () => useApiMutation<{ rows: MasterRow[] }, WriteResponse>("PUT", "/api/data/master");
export const usePutHolidays = () =>
  useApiMutation<{ rows: HolidayRow[] }, WriteResponse>("PUT", "/api/data/holidays");
