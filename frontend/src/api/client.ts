import type { components } from "./schema";

type S = components["schemas"];
export type ContextResponse = S["ContextResponse"];
export type FleetResponse = S["FleetResponse"];
export type FleetAtm = S["FleetAtm"];
export type AtmResponse = S["AtmResponse"];
export type AccuracyResponse = S["AccuracyResponse"];
export type PlanRequest = S["PlanRequest"];
export type PlanResponse = S["PlanResponse"];
export type StatusResponse = S["StatusResponse"];
export type OverridesRequest = S["OverridesRequest"];
export type SL = "p50" | "p80" | "p90" | "p95";

export class ApiRequestError extends Error {
  status: number;
  code: string;
  details?: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Same-origin JSON fetch (dev: Vite proxies /api; demo: FastAPI serves both). Errors follow TR-35 {error:{code,message,details}}. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers:
      init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json", ...init.headers }
        : init?.headers,
  });
  if (!res.ok) {
    let code = "HTTP_ERROR";
    let message = `${res.status} ${res.statusText}`;
    let details: unknown;
    try {
      const j = await res.json();
      code = j.error?.code ?? code;
      message = j.error?.message ?? message;
      details = j.error?.details;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiRequestError(res.status, code, message, details);
  }
  return (await res.json()) as T;
}

export function qs(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}
