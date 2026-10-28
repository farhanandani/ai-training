import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ValidationPanel } from "./ValidationPanel";

const issues = [
  { severity: "info" as const, code: "INFERRED_MASTER", message: "master inferred", tid: "TID-B", date: null },
  { severity: "error" as const, code: "BAD_DATE", message: "bad date x", tid: "TID-A", date: null },
  { severity: "warning" as const, code: "GAP", message: "gap found", tid: "TID-B", date: "2026-01-02" },
];

describe("ValidationPanel", () => {
  it("groups by severity (error, warning, info) and filters by TID", () => {
    render(<ValidationPanel issues={issues} />);
    const heads = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(heads).toEqual(["Errors (1)", "Warnings (1)", "Info (1)"]);
    expect(screen.getByText("bad date x")).toBeTruthy();
    expect(screen.getByText("gap found")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Filter by TID"), { target: { value: "TID-B" } });
    expect(screen.queryByText("bad date x")).toBeNull();
    const warn = screen.getByText("gap found");
    expect(within(warn.closest("section")!).getByText("gap found")).toBeTruthy();
    expect(screen.getByText("master inferred")).toBeTruthy();
  });

  it("shows only the first 50 rows of a group", () => {
    const many = Array.from({ length: 60 }, (_, i) => ({
      severity: "error" as const, code: "BAD_AMOUNT", message: `row ${i}`, tid: "T", date: null,
    }));
    render(<ValidationPanel issues={many} />);
    expect(screen.getByText("Errors (60)")).toBeTruthy();
    expect(screen.getByText("row 49")).toBeTruthy();
    expect(screen.queryByText("row 50")).toBeNull();
  });
});
