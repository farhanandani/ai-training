const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ID = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });

/** 640000000 -> "Rp 640.000.000" (PRD 7). */
export function formatRp(n: number): string {
  const v = Math.round(n);
  return `${v < 0 ? "-" : ""}Rp ${ID.format(Math.abs(v))}`;
}

/** Compact for tiles: >= 1e9 -> "Rp 1,2 M" (1 decimal), >= 1e6 -> "Rp 640 jt" (no decimals). */
export function formatRpCompact(n: number): string {
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  if (a >= 1e9) return `${sign}Rp ${(a / 1e9).toFixed(1).replace(".", ",")} M`;
  if (a >= 1e6) return `${sign}Rp ${ID.format(Math.round(a / 1e6))} jt`;
  return formatRp(n);
}

/** "2026-03-12" -> "12 Mar 2026" (no Date parsing, so no timezone shift). */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}
