import { describe, expect, it } from "vitest";
import { buildSankeyOption } from "./sankeyOption";

const names = { A1: "Harapan Indah Residence", B2: "Terminal Station", C3: "Airport Hub" };
const flows = [
  { from_tid: "A1", to_tid: "B2", amount: 300_000_000 },
  { from_tid: "A1", to_tid: "C3", amount: 150_000_000 },
  { from_tid: "B2", to_tid: "C3", amount: 50_000_000 },
];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const series = (o: any) => o.series[0];

describe("buildSankeyOption", () => {
  const opt = buildSankeyOption(flows, names);

  it("keeps every link amount", () => {
    const links = series(opt).links as { source: string; target: string; value: number }[];
    expect(links.map((l) => l.value)).toEqual([300_000_000, 150_000_000, 50_000_000]);
    expect(links[0]).toMatchObject({ source: "↑ Harapan Indah Residence", target: "↓ Terminal Station" });
  });

  it("keeps donor and receiver nodes distinct, so a TID in both roles cannot form a cycle", () => {
    const nodes = (series(opt).data as { name: string }[]).map((n) => n.name);
    expect(nodes).toContain("↑ Terminal Station");
    expect(nodes).toContain("↓ Terminal Station");
    expect(new Set(nodes).size).toBe(nodes.length);
  });

  it("falls back to the TID when the name is unknown", () => {
    const o = buildSankeyOption([{ from_tid: "Z9", to_tid: "A1", amount: 1 }], names);
    expect(series(o).links[0].source).toBe("↑ Z9");
  });
});
