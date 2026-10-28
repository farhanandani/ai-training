import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { AtmResponse } from "../../api/client";
import { buildDemandOption } from "./chartOptions";

export function DemandForecastChart({ atm, height = 340 }: { atm: AtmResponse; height?: number }) {
  const option = useMemo(() => buildDemandOption(atm), [atm]);
  return (
    <ReactECharts option={option} style={{ height, width: "100%" }} notMerge opts={{ renderer: "canvas" }} />
  );
}
