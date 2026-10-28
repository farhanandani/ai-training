import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useVersionedState } from "./useVersionedState";

describe("useVersionedState", () => {
  it("keeps edits while the dataset_version is unchanged and clears them when it changes", () => {
    const { result, rerender } = renderHook(({ v }) => useVersionedState<Record<string, number>>(v, {}), {
      initialProps: { v: 1 },
    });
    act(() => result.current[1]({ "TID|2026-03-06": 5 }));
    rerender({ v: 1 });
    expect(Object.keys(result.current[0])).toHaveLength(1);
    rerender({ v: 2 }); // reset / upload / another save bumped the version
    expect(result.current[0]).toEqual({});
  });
});
