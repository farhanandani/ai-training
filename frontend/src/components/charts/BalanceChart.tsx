import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { AtmResponse } from "../../api/client";
import { buildBalanceOption } from "./chartOptions";

export function BalanceChart({ atm, height = 340 }: { atm: AtmResponse; height?: number }) {
  const option = useMemo(() => buildBalanceOption(atm), [atm]);
  return (
    <ReactECharts option={option} style={{ height, width: "100%" }} notMerge opts={{ renderer: "canvas" }} />
  );
}
