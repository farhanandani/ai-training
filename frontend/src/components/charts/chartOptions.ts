import type { EChartsOption } from "echarts";
import type { AtmResponse } from "../../api/client";
import { formatDate, formatRp, formatRpCompact } from "../../lib/format";
import { COLORS, baseOption, xAxisBase, yAxisBase } from "./chartTheme";

const ZOOM_DAYS = 90;

type Num = number | null;
interface TipItem {
  seriesName: string;
  value: unknown;
  marker: string;
  axisValue: string;
}

const sortedUnique = (xs: string[]) => [...new Set(xs)].sort();
const byDate = <T extends { date: string }>(rows: T[]) => new Map(rows.map((r) => [r.date, r]));

/** Default window: last 90 days of history plus the whole forecast. */
function zoom(dates: string[], atm: AtmResponse) {
  const histDates = atm.history.map((h) => h.date);
  const start = histDates[Math.max(0, histDates.length - ZOOM_DAYS)] ?? dates[0];
  const end = dates[dates.length - 1];
  return [
    { type: "inside" as const, startValue: start, endValue: end },
    {
      type: "slider" as const,
      startValue: start,
      endValue: end,
      height: 22,
      bottom: 10,
      borderColor: COLORS.grid,
      fillerColor: "rgba(37,99,235,0.08)",
    },
  ];
}

/** Dates of the Lebaran window: Idul Fitri days plus the Idul Fitri collective-leave days around them. */
function lebaranDates(atm: AtmResponse): string[] {
  return atm.holidays_in_view
    .filter(
      (h) => h.type === "idul_fitri" || (h.type === "cuti_bersama" && /idul fitri|lebaran/i.test(h.name)),
    )
    .map((h) => h.date)
    .sort();
}

function holidayAreas(atm: AtmResponse, axis: Set<string>) {
  const leb = lebaranDates(atm).filter((d) => axis.has(d));
  const lebSet = new Set(leb);
  const areas: unknown[] = [];
  for (const h of atm.holidays_in_view) {
    if (lebSet.has(h.date) || !axis.has(h.date)) continue;
    // other holidays: light shading, the name shows in the tooltip
    areas.push([
      { name: h.name, xAxis: h.date, itemStyle: { color: COLORS.holiday }, label: { show: false } },
      { xAxis: h.date },
    ]);
  }
  if (leb.length) {
    areas.push([
      {
        name: "Lebaran",
        xAxis: leb[0],
        itemStyle: { color: COLORS.lebaran },
        label: { show: true, position: "insideTop", color: COLORS.lebaranText, fontWeight: 600 },
      },
      { xAxis: leb[leb.length - 1] },
    ]);
  }
  return areas;
}

export function buildDemandOption(atm: AtmResponse): EChartsOption {
  const dates = sortedUnique([
    ...atm.history.map((h) => h.date),
    ...atm.forecast.map((f) => f.date),
    ...(atm.actual_after ?? []).map((a) => a.date),
  ]);
  const hist = byDate(atm.history);
  const fc = byDate(atm.forecast);
  const after = byDate(atm.actual_after ?? []);
  const holidayNames = new Map<string, string[]>();
  for (const h of atm.holidays_in_view)
    holidayNames.set(h.date, [...(holidayNames.get(h.date) ?? []), h.name]);

  const col = <T>(m: Map<string, T>, f: (r: T) => number): Num[] =>
    dates.map((d) => (m.has(d) ? f(m.get(d)!) : null));
  const q10 = col(fc, (r) => r.q10);
  const q90 = col(fc, (r) => r.q90);
  const span = dates.map((_, i) => (q10[i] === null || q90[i] === null ? null : q90[i]! - q10[i]!));
  const axis = new Set(dates);

  const series: unknown[] = [
    {
      name: "band_low",
      type: "line",
      stack: "band",
      data: q10,
      symbol: "none",
      lineStyle: { opacity: 0 },
      areaStyle: { opacity: 0 },
      silent: true,
    },
    {
      name: "band_span",
      type: "line",
      stack: "band",
      data: span,
      symbol: "none",
      lineStyle: { opacity: 0 },
      areaStyle: { color: COLORS.band },
      silent: true,
    },
    {
      name: "actual",
      type: "line",
      data: col(hist, (r) => r.withdrawal),
      symbol: "none",
      lineStyle: { width: 1.6, color: COLORS.actual },
      itemStyle: { color: COLORS.actual },
    },
    {
      name: "q50",
      type: "line",
      data: col(fc, (r) => r.q50),
      symbol: "none",
      lineStyle: { width: 2.2, color: COLORS.forecast },
      itemStyle: { color: COLORS.forecast },
      markArea: { silent: true, data: holidayAreas(atm, axis) },
    },
  ];
  if (atm.actual_after?.length) {
    series.push({
      name: "actual_after",
      type: "line",
      data: col(after, (r) => r.withdrawal),
      symbol: "circle",
      symbolSize: 4,
      lineStyle: { width: 1.6, type: "dashed", color: COLORS.actual },
      itemStyle: { color: COLORS.actual },
    });
  }

  const labels: Record<string, string> = {
    actual: "Actual withdrawal",
    q50: "Forecast (p50)",
    actual_after: "Actual after as-of",
  };
  return {
    ...baseOption,
    legend: {
      ...baseOption.legend,
      data: ["actual", "q50", ...(atm.actual_after?.length ? ["actual_after"] : [])],
      formatter: (n: string) => labels[n] ?? n,
    },
    tooltip: {
      ...baseOption.tooltip,
      formatter: (p: unknown) => {
        const items = p as TipItem[];
        const day = items[0]?.axisValue ?? "";
        const rows: string[] = [`<b>${formatDate(day)}</b>`];
        for (const h of holidayNames.get(day) ?? []) rows.push(`<i>${h}</i>`);
        for (const it of items) {
          if (it.seriesName === "band_low" || it.value == null) continue;
          if (it.seriesName === "band_span") {
            const f = fc.get(day);
            if (f)
              rows.push(`${it.marker} p10 to p90: ${formatRpCompact(f.q10)} to ${formatRpCompact(f.q90)}`);
            continue;
          }
          rows.push(
            `${it.marker} ${labels[it.seriesName] ?? it.seriesName}: ${formatRp(it.value as number)}`,
          );
        }
        return rows.join("<br/>");
      },
    },
    xAxis: { ...xAxisBase, data: dates },
    yAxis: { ...yAxisBase },
    dataZoom: zoom(dates, atm),
    series: series as EChartsOption["series"],
  } as EChartsOption;
}

export function buildBalanceOption(atm: AtmResponse): EChartsOption {
  const cur = byDate(atm.projection.current);
  const rec = byDate(atm.projection.recommended);
  const hist = byDate(atm.history);
  const dates = sortedUnique([
    ...atm.history.map((h) => h.date),
    ...atm.projection.current.map((p) => p.date),
    ...atm.projection.recommended.map((p) => p.date),
  ]);
  const col = <T>(m: Map<string, T>, f: (r: T) => number): Num[] =>
    dates.map((d) => (m.has(d) ? f(m.get(d)!) : null));
  const min = atm.master.min_safe_balance;
  const visitById = new Map(atm.visits.map((v) => [v.date, v]));

  const visitPoints = atm.visits.map((v) => ({
    value: [v.date, rec.get(v.date)?.p50 ?? cur.get(v.date)?.p50 ?? min],
    itemStyle: { color: v.kind === "extra" ? COLORS.extraVisit : COLORS.recommended },
  }));

  const series: unknown[] = [
    {
      name: "actual_balance",
      type: "line",
      data: col(hist, (r) => r.closing_balance),
      symbol: "none",
      lineStyle: { width: 1.6, color: COLORS.actual },
      itemStyle: { color: COLORS.actual },
      markPoint: {
        symbol: "triangle",
        symbolSize: 9,
        itemStyle: { color: COLORS.recommended },
        label: { show: false },
        data: atm.history
          .filter((h) => h.replenishment > 0)
          .map((h) => ({
            name: "Replenishment",
            coord: [h.date, h.closing_balance],
            value: h.replenishment,
          })),
      },
    },
    {
      name: "current_projection",
      type: "line",
      data: col(cur, (r) => r.p50),
      symbol: "none",
      lineStyle: { width: 2, color: COLORS.current },
      itemStyle: { color: COLORS.current },
    },
    {
      name: "current_projection_p90",
      type: "line",
      data: col(cur, (r) => r.p90),
      symbol: "none",
      lineStyle: { width: 1.2, color: COLORS.current, type: "dotted" },
      itemStyle: { color: COLORS.current },
    },
    {
      name: "recommended_projection",
      type: "line",
      data: col(rec, (r) => r.p50),
      symbol: "none",
      lineStyle: { width: 2.2, color: COLORS.recommended },
      itemStyle: { color: COLORS.recommended },
      markLine: {
        silent: true,
        symbol: "none",
        lineStyle: { color: COLORS.risk, type: "dashed", width: 1.4 },
        label: { formatter: "Min safe balance", color: COLORS.risk, position: "insideEndTop" },
        data: [{ name: "Min safe balance", yAxis: min }],
      },
    },
    {
      name: "visits",
      type: "scatter",
      data: visitPoints,
      symbol: "diamond",
      symbolSize: 11,
      label: { show: false },
      z: 5,
    },
  ];

  const labels: Record<string, string> = {
    actual_balance: "Actual balance",
    current_projection: "Current policy (p50)",
    current_projection_p90: "Current policy (p90)",
    recommended_projection: "Recommended plan",
    visits: "Visits",
  };
  return {
    ...baseOption,
    legend: { ...baseOption.legend, formatter: (n: string) => labels[n] ?? n },
    tooltip: {
      ...baseOption.tooltip,
      formatter: (p: unknown) => {
        const items = p as TipItem[];
        const day = items[0]?.axisValue ?? "";
        const rows: string[] = [`<b>${formatDate(day)}</b>`];
        const h = hist.get(day);
        if (h && h.replenishment > 0) rows.push(`Replenished ${formatRp(h.replenishment)}`);
        for (const it of items) {
          if (it.value == null || it.seriesName === "visits") continue;
          rows.push(
            `${it.marker} ${labels[it.seriesName] ?? it.seriesName}: ${formatRp(it.value as number)}`,
          );
        }
        const v = visitById.get(day);
        if (v) rows.push(`Visit (${v.kind}): ${formatRp(v.amount)}<br/><i>${v.reason}</i>`);
        return rows.join("<br/>");
      },
    },
    xAxis: { ...xAxisBase, data: dates },
    yAxis: { ...yAxisBase, max: atm.master.capacity },
    dataZoom: zoom(dates, atm),
    series: series as EChartsOption["series"],
  } as EChartsOption;
}
