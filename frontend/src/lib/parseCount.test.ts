import { describe, expect, it } from "vitest";
import { parseCount } from "./parseCount";

describe("parseCount", () => {
  it("accepts plain digits and id-ID grouped numbers", () => {
    expect(parseCount("1500000")).toBe(1500000);
    expect(parseCount("1.500.000")).toBe(1500000);
    expect(parseCount("0")).toBe(0);
  });
  it.each(["1.5", "2.50", "-5", "", "1,5", "12.34.567", "abc"])("rejects %j", (v) => {
    expect(parseCount(v)).toBeNull();
  });
});
