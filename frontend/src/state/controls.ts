import { create } from "zustand";
import type { ContextResponse, SL } from "../api/client";

export const SLS: SL[] = ["p50", "p80", "p90", "p95"];
export const H_MIN = 7;
export const H_MAX = 30;

interface ControlsState {
  scenario: string; // scenario id, "custom" once as-of/h is edited by hand, "" before the context loads
  asOf: string; // ISO date, "" until the context has loaded
  h: number;
  sl: SL;
  ctx: ContextResponse | null;
  setContext: (ctx: ContextResponse) => void;
  setScenario: (id: string) => void;
  setAsOf: (d: string) => void;
  setH: (h: number) => void;
  setSl: (sl: SL) => void;
}

const clampH = (h: number) => Math.min(H_MAX, Math.max(H_MIN, Math.round(h)));
const isSl = (v: unknown): v is SL => SLS.includes(v as SL);

function clampDate(d: string, ctx: ContextResponse): string {
  return d < ctx.as_of_min ? ctx.as_of_min : d > ctx.as_of_max ? ctx.as_of_max : d;
}

/** Keep ?as_of=&h=&sl= in the address bar (bookmarkable demo views) without adding history entries. */
function writeUrl(s: { asOf: string; h: number; sl: SL }) {
  try {
    const url = new URL(window.location.href);
    if (s.asOf) url.searchParams.set("as_of", s.asOf);
    url.searchParams.set("h", String(s.h));
    url.searchParams.set("sl", s.sl);
    window.history.replaceState(window.history.state, "", url);
  } catch {
    /* non-browser environment */
  }
}

function matchScenario(ctx: ContextResponse, asOf: string, h: number): string {
  return ctx.scenarios.find((s) => s.as_of === asOf && s.h === h)?.id ?? "custom";
}

export const useControls = create<ControlsState>((set, get) => ({
  scenario: "",
  asOf: "",
  h: 14,
  sl: "p90",
  ctx: null,

  setContext: (ctx) => {
    const cur = get();
    const q = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
    const fromUrl = cur.asOf === "" && q.get("as_of");
    let asOf = cur.asOf;
    let h = cur.h;
    let sl = cur.sl;
    if (cur.asOf === "") {
      // first load: URL wins, otherwise the default scenario
      const def = ctx.scenarios.find((s) => s.id === ctx.default_scenario) ?? ctx.scenarios[0];
      asOf = fromUrl ? q.get("as_of")! : (def?.as_of ?? ctx.as_of_max);
      const hq = Number(q.get("h"));
      h =
        q.get("h") && Number.isFinite(hq)
          ? clampH(hq)
          : fromUrl
            ? ((ctx.defaults.h as number) ?? 14)
            : (def?.h ?? 14);
      const slq = q.get("sl");
      sl = isSl(slq) ? slq : isSl(ctx.defaults.sl) ? (ctx.defaults.sl as SL) : "p90";
    }
    asOf = clampDate(asOf, ctx);
    const next = { ctx, asOf, h, sl, scenario: matchScenario(ctx, asOf, h) };
    set(next);
    writeUrl(next);
  },

  setScenario: (id) => {
    const { ctx } = get();
    const sc = ctx?.scenarios.find((s) => s.id === id);
    if (!ctx || !sc) return;
    const next = { scenario: id, asOf: clampDate(sc.as_of, ctx), h: clampH(sc.h) };
    set(next);
    writeUrl({ ...next, sl: get().sl });
  },

  setAsOf: (d) => {
    const { ctx, h, sl } = get();
    const asOf = ctx ? clampDate(d, ctx) : d;
    set({ asOf, scenario: ctx ? matchScenario(ctx, asOf, h) : "custom" });
    writeUrl({ asOf, h, sl });
  },

  setH: (hIn) => {
    const { ctx, asOf, sl } = get();
    const h = clampH(hIn);
    set({ h, scenario: ctx ? matchScenario(ctx, asOf, h) : "custom" });
    writeUrl({ asOf, h, sl });
  },

  setSl: (sl) => {
    set({ sl });
    writeUrl({ ...get(), sl });
  },
}));
