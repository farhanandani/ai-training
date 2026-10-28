// Calm palette shared by both charts. Status colours match StatusBadge (red / amber / green).
export const COLORS = {
  text: "#334155", // slate-700
  muted: "#64748b", // slate-500
  grid: "#e2e8f0", // slate-200
  actual: "#475569", // slate-600
  forecast: "#2563eb", // blue-600
  band: "rgba(37, 99, 235, 0.16)",
  recommended: "#16a34a", // green-600, the plan we suggest
  current: "#d97706", // amber-600, the current policy
  risk: "#dc2626", // red-600
  extraVisit: "#7c3aed", // violet-600
  holiday: "rgba(148, 163, 184, 0.16)",
  lebaran: "rgba(244, 63, 94, 0.13)",
  lebaranText: "#be123c",
} as const;

/** Axis tick in IDR millions: 640000000 -> "640". The axis name carries the unit. */
export const millions = (v: number) => `${Math.round(v / 1e6).toLocaleString("en-US")}`;

/** "2026-03-12" -> "12 Mar" */
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const shortDate = (iso: string) => `${Number(iso.slice(8, 10))} ${MON[Number(iso.slice(5, 7)) - 1]}`;

export const baseOption = {
  animation: false,
  textStyle: { color: COLORS.text, fontFamily: "inherit" },
  grid: { left: 56, right: 24, top: 68, bottom: 72 },
  legend: { top: 4, left: 0, itemWidth: 18, itemHeight: 8, textStyle: { color: COLORS.text, fontSize: 12 } },
  tooltip: {
    trigger: "axis" as const,
    confine: true,
    axisPointer: { type: "line" as const, lineStyle: { color: COLORS.muted, type: "dashed" as const } },
    backgroundColor: "#ffffff",
    borderColor: COLORS.grid,
    textStyle: { color: COLORS.text, fontSize: 12 },
  },
};

export const yAxisBase = {
  type: "value" as const,
  name: "Rp million",
  nameTextStyle: { color: COLORS.muted, align: "left" as const },
  axisLabel: { color: COLORS.muted, formatter: millions },
  splitLine: { lineStyle: { color: COLORS.grid } },
};

export const xAxisBase = {
  type: "category" as const,
  boundaryGap: true,
  axisLine: { lineStyle: { color: COLORS.grid } },
  axisLabel: { color: COLORS.muted, hideOverlap: true, formatter: shortDate },
  axisTick: { show: false },
};
