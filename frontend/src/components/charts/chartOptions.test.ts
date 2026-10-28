import { describe, expect, it } from "vitest";
import fixture from "./__fixtures__/atm-jkt0007.json";
import type { AtmResponse } from "../../api/client";
import { buildBalanceOption, buildDemandOption } from "./chartOptions";

const atm = fixture as unknown as AtmResponse;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const seriesOf = (opt: any, name: string) => (opt.series as any[]).find((s) => s.name === name);

describe("buildDemandOption", () => {
  const opt = buildDemandOption(atm);

  it("has actual, q50 and a stacked q10-q90 band", () => {
    expect(seriesOf(opt, "actual")).toBeTruthy();
    expect(seriesOf(opt, "q50")).toBeTruthy();
    const low = seriesOf(opt, "band_low");
    const span = seriesOf(opt, "band_span");
    expect(low.stack).toBeTruthy();
    expect(span.stack).toBe(low.stack);
    // q10 + (q90 - q10) = q90 on the first forecast day
    const f = atm.forecast[0];
    const idx = (opt.xAxis as { data: string[] }).data.indexOf(f.date);
    expect(low.data[idx] + span.data[idx]).toBeCloseTo(f.q90);
  });

  it("labels the Lebaran window when the view covers 2026-03-20", () => {
    const areas = (seriesOf(opt, "q50").markArea.data as { name?: string }[][]).flat();
    const leb = areas.filter((a) => a.name === "Lebaran");
    expect(leb.length).toBeGreaterThan(0);
    expect(
      (seriesOf(opt, "q50").markArea.data as { xAxis: string }[][]).some(
        (p) => p[0].xAxis <= "2026-03-20" && p[1].xAxis >= "2026-03-21",
      ),
    ).toBe(true);
  });

  it("draws actual_after dashed", () => {
    expect(seriesOf(opt, "actual_after").lineStyle.type).toBe("dashed");
  });

  it("defaults dataZoom to the last 90 days of history plus the forecast", () => {
    const dz = (opt.dataZoom as { startValue: string; endValue: string }[])[0];
    const hist = atm.history;
    expect(dz.startValue >= hist[Math.max(0, hist.length - 90)].date).toBe(true);
    expect(dz.endValue).toBe(atm.forecast[atm.forecast.length - 1].date);
  });
});

describe("buildBalanceOption", () => {
  const opt = buildBalanceOption(atm);

  it("has the min-safe markLine equal to master.min_safe_balance", () => {
    const ml = seriesOf(opt, "recommended_projection").markLine.data[0];
    expect(ml.yAxis).toBe(atm.master.min_safe_balance);
  });

  it("has actual balance with replenishment markPoints, both projections and visit markers", () => {
    const ab = seriesOf(opt, "actual_balance");
    const jumps = atm.history.filter((p) => p.replenishment > 0).length;
    expect(ab.markPoint.data.length).toBe(jumps);
    expect(seriesOf(opt, "current_projection")).toBeTruthy();
    expect(seriesOf(opt, "recommended_projection")).toBeTruthy();
    expect(seriesOf(opt, "visits").data.length).toBe(atm.visits.length);
  });
});
