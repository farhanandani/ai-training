import { describe, expect, it } from "vitest";
import { formatDate, formatMillions, formatRp, formatRpCompact } from "./format";

describe("format", () => {
  it("formatMillions uses dot thousands separators", () => {
    expect(formatMillions(1000)).toBe("1.000");
  });
  it("formatRp uses dot thousands separators", () => {
    expect(formatRp(640000000)).toBe("Rp 640.000.000");
  });
  it("formatRpCompact uses jt below 1e9", () => {
    expect(formatRpCompact(640000000)).toBe("Rp 640 jt");
  });
  it("formatRpCompact uses M with one decimal from 1e9", () => {
    expect(formatRpCompact(1234500000)).toBe("Rp 1,2 M");
  });
  it("formatRpCompact rolls values that round to 1000 jt over to M", () => {
    expect(formatRpCompact(999_500_000)).toBe("Rp 1,0 M");
  });
  it("formatDate is English day-month-year", () => {
    expect(formatDate("2026-03-12")).toBe("12 Mar 2026");
  });
});
