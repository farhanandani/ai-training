import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import type { BacktestPoint } from "../../api/client";
import { formatDate, formatRp } from "../../lib/format";
import { COLORS, baseOption, xAxisBase, yAxisBase } from "./chartTheme";

interface TipItem {
  seriesName: string;
  value: unknown;
  marker: string;
  axisValue: string;
}

/** Actual vs q50 with the q10-q90 band for one backtest origin. */
function buildBacktestOption(points: BacktestPoint[], origin: string): EChartsOption {
  const pts = points.filter((p) => p.origin === origin).sort((a, b) => a.date.localeCompare(b.date));
  const dates = pts.map((p) => p.date);
  const q10 = pts.map((p) => p.q10);
  const span = pts.map((p) => (p.q10 == null || p.q90 == null ? null : p.q90 - p.q10));
  const labels: Record<string, string> = { y: "Actual withdrawal", q50: "Forecast (p50)" };
  return {
    ...baseOption,
    legend: { ...baseOption.legend, data: ["y", "q50"], formatter: (n: string) => labels[n] ?? n },
    tooltip: {
      ...baseOption.tooltip,
      formatter: (p: unknown) => {
        const items = p as TipItem[];
        const day = items[0]?.axisValue ?? "";
        const pt = pts.find((x) => x.date === day);
        const rows = [`<b>${formatDate(day)}</b>`];
        for (const it of items) {
          if (it.seriesName === "band_low" || it.value == null) continue;
          if (it.seriesName === "band_span") {
            if (pt?.q10 != null && pt.q90 != null)
              rows.push(`${it.marker} p10 to p90: ${formatRp(pt.q10)} to ${formatRp(pt.q90)}`);
            continue;
          }
          rows.push(`${it.marker} ${labels[it.seriesName] ?? it.seriesName}: ${formatRp(it.value as number)}`);
        }
        return rows.join("<br/>");
      },
    },
    xAxis: { ...xAxisBase, data: dates },
    yAxis: { ...yAxisBase },
    series: [
      { name: "band_low", type: "line", stack: "band", data: q10, symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, silent: true },
      { name: "band_span", type: "line", stack: "band", data: span, symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: COLORS.band }, silent: true },
      { name: "y", type: "line", data: pts.map((p) => p.y), symbol: "circle", symbolSize: 4, lineStyle: { width: 1.6, color: COLORS.actual }, itemStyle: { color: COLORS.actual } },
      { name: "q50", type: "line", data: pts.map((p) => p.q50), symbol: "none", lineStyle: { width: 2.2, color: COLORS.forecast }, itemStyle: { color: COLORS.forecast } },
    ] as EChartsOption["series"],
  } as EChartsOption;
}

export function BacktestChart({ points, origin, height = 320 }: { points: BacktestPoint[]; origin: string; height?: number }) {
  const option = useMemo(() => buildBacktestOption(points, origin), [points, origin]);
  return (
    <ReactECharts option={option} style={{ height, width: "100%" }} notMerge opts={{ renderer: "canvas" }} />
  );
}
