/** Strict non-negative integer: plain digits, or id-ID grouped (1.500.000). Anything else (1.5, 2.50, -5, "") is null. */
export function parseCount(v: unknown): number | null {
  const t = String(v ?? "").trim();
  if (/^\d+$/.test(t)) return Number(t);
  if (/^\d{1,3}(\.\d{3})+$/.test(t)) return Number(t.replace(/\./g, ""));
  return null;
}
