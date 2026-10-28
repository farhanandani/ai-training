import type { EChartsOption } from "echarts";
import { formatRp } from "../../lib/format";
import { COLORS } from "./chartTheme";

export interface Flow {
  from_tid: string;
  to_tid: string;
  amount: number;
}

/** Donor nodes are "↑ name", receiver nodes "↓ name": the same ATM in both roles can never form a cycle. */
export function buildSankeyOption(flows: Flow[], names: Record<string, string>): EChartsOption {
  const nm = (tid: string) => names[tid] ?? tid;
  const donors = [...new Set(flows.map((f) => `↑ ${nm(f.from_tid)}`))];
  const receivers = [...new Set(flows.map((f) => `↓ ${nm(f.to_tid)}`))];
  return {
    animation: false,
    textStyle: { color: COLORS.text, fontFamily: "inherit" },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: "#ffffff",
      borderColor: COLORS.grid,
      textStyle: { color: COLORS.text, fontSize: 12 },
      formatter: (p: unknown) => {
        const q = p as { dataType: string; name: string; value: number; data: { source?: string; target?: string } };
        return q.dataType === "edge"
          ? `${q.data.source} &rarr; ${q.data.target}<br/><b>${formatRp(q.value)}</b>`
          : q.name;
      },
    },
    series: [
      {
        type: "sankey",
        left: 8,
        right: 150,
        top: 8,
        bottom: 8,
        nodeWidth: 14,
        nodeGap: 14,
        draggable: false,
        emphasis: { focus: "adjacency" },
        lineStyle: { color: "gradient", opacity: 0.45, curveness: 0.5 },
        label: { color: COLORS.text, fontSize: 12 },
        data: [
          ...donors.map((name) => ({ name, itemStyle: { color: COLORS.current } })),
          ...receivers.map((name) => ({ name, itemStyle: { color: COLORS.risk } })),
        ],
        links: flows.map((f) => ({
          source: `↑ ${nm(f.from_tid)}`,
          target: `↓ ${nm(f.to_tid)}`,
          value: f.amount,
        })),
      },
    ],
  };
}
