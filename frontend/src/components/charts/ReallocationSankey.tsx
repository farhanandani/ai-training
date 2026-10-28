import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { buildSankeyOption, type Flow } from "./sankeyOption";

export function ReallocationSankey({ flows, names }: { flows: Flow[]; names: Record<string, string> }) {
  const option = useMemo(() => buildSankeyOption(flows, names), [flows, names]);
  if (flows.length === 0)
    return (
      <div>
        <p className="py-10 text-center text-sm text-slate-500">No re-allocation needed at this budget.</p>
        <span hidden data-testid="sankey-links-count">
          0
        </span>
      </div>
    );
  const donors = new Set(flows.map((f) => f.from_tid)).size;
  const height = Math.max(240, Math.max(donors, new Set(flows.map((f) => f.to_tid)).size) * 44 + 40);
  return (
    <div>
      <ReactECharts option={option} style={{ height, width: "100%" }} notMerge opts={{ renderer: "canvas" }} />
      <p className="text-xs text-slate-500">
        <span data-testid="sankey-links-count">{flows.length}</span> transfer{flows.length === 1 ? "" : "s"}{" "}
        from over-stocked ATMs (↑) to at-risk ATMs (↓)
      </p>
    </div>
  );
}
