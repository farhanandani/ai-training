import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useControls } from "../state/controls";
import { PlannerPage } from "./Planner";

// canvas / grid are not testable in jsdom; the page structure is what matters here
vi.mock("../components/PlanGrid", () => ({ PlanGrid: () => <div /> }));
vi.mock("../components/charts/ReallocationSankey", () => ({ ReallocationSankey: () => <div /> }));

const stats = { cash_out_days: 0, idle_cash: 0, idle_cost: 0, visits: 0, visit_cost: 0, loaded: 0 };
const plan = (budget: number | null) => ({
  as_of: "2026-03-06", h: 14, sl: "p90", budget, dataset_version: 1, pending_tids: [], job_id: null,
  need_total: 1_000_000_000, funded_total: 1_000_000_000, funded_pct: 1, unused: 0, underfunded: 0,
  visits: [], reallocation: [], comparison: { current: stats, recommended: stats, replay: null },
});

describe("PlannerPage", () => {
  it("keeps the budget input mounted while the plan refetches", async () => {
    useControls.setState({ asOf: "2026-03-06", h: 14, sl: "p90" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        let body: unknown = {};
        if (url.startsWith("/api/context")) body = { dataset_version: 1 };
        else if (url.startsWith("/api/fleet")) body = { atms: [], pending_tids: [] };
        else if (url.startsWith("/api/settings")) body = { overstock_frac: 0.5, idle_rate: 0.05 };
        else if (url.startsWith("/api/plan")) {
          await new Promise((r) => setTimeout(r, 80)); // slow enough to observe the refetch
          body = plan(JSON.parse(String(init?.body)).budget);
        }
        return new Response(JSON.stringify(body), { status: 200 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <PlannerPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByLabelText("Unconstrained"));
    const input = (await screen.findByLabelText("Budget (IDR)")) as HTMLInputElement;
    input.focus();
    fireEvent.change(input, { target: { value: "5000000000" } });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 450)); // debounce fires -> new plan query key -> refetch
    });
    expect(screen.getByLabelText("Budget (IDR)")).toBe(input);
    expect(document.activeElement).toBe(input);
    await waitFor(() => expect(screen.queryByText(/Updating/)).toBeNull());
    expect(screen.getByLabelText("Budget (IDR)")).toBe(input);
    expect(input.value).toBe("5.000.000.000");
  });
});
