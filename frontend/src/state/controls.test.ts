import { beforeEach, describe, expect, it } from "vitest";
import { useControls } from "./controls";
import type { ContextResponse } from "../api/client";

const ctx = {
  data_source: "Dummy",
  min_date: "2024-01-01",
  max_date: "2026-04-30",
  as_of_min: "2024-10-01",
  as_of_max: "2026-04-16",
  tids: ["1001"],
  scenarios: [
    { id: "today", label: "Today", as_of: "2026-04-16", h: 14 },
    { id: "pre_lebaran_2026", label: "Pre-Lebaran 2026", as_of: "2026-03-06", h: 21 },
  ],
  default_scenario: "pre_lebaran_2026",
  defaults: { h: 14, sl: "p90" },
  dataset_version: 1,
} as unknown as ContextResponse;

describe("controls store", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    useControls.setState({ scenario: "", asOf: "", h: 14, sl: "p90", ctx: null });
  });

  it("setScenario applies the scenario as-of and horizon", () => {
    useControls.getState().setContext(ctx);
    useControls.getState().setScenario("pre_lebaran_2026");
    const s = useControls.getState();
    expect(s.asOf).toBe("2026-03-06");
    expect(s.h).toBe(21);
  });

  it("setContext applies the default scenario when the URL has no query", () => {
    useControls.getState().setContext(ctx);
    expect(useControls.getState().scenario).toBe("pre_lebaran_2026");
    expect(useControls.getState().asOf).toBe("2026-03-06");
  });

  it("keeps the URL query in sync", () => {
    useControls.getState().setContext(ctx);
    useControls.getState().setH(28);
    useControls.getState().setSl("p95");
    const q = new URLSearchParams(window.location.search);
    expect(q.get("as_of")).toBe("2026-03-06");
    expect(q.get("h")).toBe("28");
    expect(q.get("sl")).toBe("p95");
    expect(useControls.getState().scenario).toBe("custom");
  });

  it("clamps a URL as_of outside the allowed range", () => {
    window.history.replaceState(null, "", "/?as_of=2030-01-01&h=10");
    useControls.getState().setContext(ctx);
    expect(useControls.getState().asOf).toBe("2026-04-16");
    expect(useControls.getState().h).toBe(10);
  });

  it("an empty log (no as-of range) leaves the view unset so no read query runs", () => {
    const empty = {
      ...ctx,
      min_date: null,
      max_date: null,
      as_of_min: null,
      as_of_max: null,
      scenarios: ctx.scenarios.map((s) => ({ ...s, in_range: false })),
    } as unknown as ContextResponse;
    useControls.getState().setContext(empty);
    const st = useControls.getState();
    expect(st.ctx).toBe(empty);
    expect(st.asOf).toBe("");
    expect(st.scenario).toBe("");
  });

  it("setScenario ignores a scenario outside the data range", () => {
    const c = {
      ...ctx,
      scenarios: ctx.scenarios.map((s) => ({ ...s, in_range: s.id === "today" })),
    } as unknown as ContextResponse;
    useControls.getState().setContext(c);
    useControls.getState().setScenario("today");
    useControls.getState().setScenario("pre_lebaran_2026");
    expect(useControls.getState().scenario).toBe("today");
    expect(useControls.getState().asOf).toBe("2026-04-16");
  });
});
