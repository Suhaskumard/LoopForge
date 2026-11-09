import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Task } from "../api/types";
import { donutSlices, heatmap, RunningNow } from "../components/Dashboard";
import { CodeView } from "../components/ui";
import { dominantKind, langOf, tokenizeLine } from "../lib/highlight";

describe("syntax highlighting", () => {
  it("classifies python keywords, strings, comments, numbers and calls", () => {
    const toks = tokenizeLine('def f(x): return len("hi") + 42  # note', "python");
    const kinds = Object.fromEntries(toks.filter((t) => t.kind !== "txt").map((t) => [t.text.trim(), t.kind]));
    expect(kinds).toMatchObject({ def: "kw", f: "fn", return: "kw", len: "bi", '"hi"': "str", "42": "num", "# note": "com" });
    expect(toks.map((t) => t.text).join("")).toBe('def f(x): return len("hi") + 42  # note'); // lossless
  });

  it("handles js and plain text, and picks a language from the path", () => {
    expect(langOf("app/main.py")).toBe("python");
    expect(langOf("src/x.tsx")).toBe("js");
    expect(langOf("README")).toBe("plain");
    expect(tokenizeLine("const a = 'x' // c", "js").map((t) => t.kind)).toEqual(["kw", "txt", "str", "txt", "com"]);
    expect(tokenizeLine("<b>hi</b>", "plain")).toEqual([{ text: "<b>hi</b>", kind: "txt" }]);
    expect(dominantKind(tokenizeLine("# a long comment", "python"))).toBe("com");
  });

  it("highlighted code is still text only, never HTML", () => {
    const { container } = render(<CodeView content={'x = "<img src=x onerror=alert(1)>"  # <script>'} path="evil.py" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByTestId("code").textContent).toContain("<img src=x onerror=alert(1)>");
  });
});

describe("dashboard math", () => {
  it("donut slices cover the circle, largest first, zeros dropped", () => {
    const s = donutSlices({ COMPLETED: 3, FAILED: 1, PENDING: 0 });
    expect(s.map((x) => x.key)).toEqual(["COMPLETED", "FAILED"]);
    expect(s[0].start).toBe(0);
    expect(s[s.length - 1].end).toBeCloseTo(1);
  });

  it("the heatmap counts tasks per day and marks future days", () => {
    const today = new Date(2026, 10, 9, 15); // a Monday
    const cols = heatmap([new Date(2026, 10, 9, 9).toISOString(), new Date(2026, 10, 9, 10).toISOString(), new Date(2026, 10, 8).toISOString()], 12, today);
    expect(cols).toHaveLength(12);
    const cells = cols.flat();
    expect(cells).toHaveLength(84);
    expect(cells.find((c) => c.day === today.toDateString())?.count).toBe(2);
    expect(cells.find((c) => c.day === new Date(2026, 10, 8).toDateString())?.count).toBe(1);
    expect(cells[cells.length - 1].count).toBe(-1); // Saturday of this week is in the future
  });

  it("running now lists only active tasks with a stage stepper", () => {
    const base = { max_iterations: 5, current_iteration: 1, created_at: "2026-11-09T00:00:00" };
    const tasks = [
      { ...base, id: "a", requirement: "Build A", status: "TESTING" },
      { ...base, id: "b", requirement: "Build B", status: "COMPLETED" },
      { ...base, id: "c", requirement: "Build C", status: "PENDING" },
    ] as unknown as Task[];
    render(<MemoryRouter><RunningNow tasks={tasks} /></MemoryRouter>);
    expect(screen.getByText("Build A")).toBeInTheDocument();
    expect(screen.queryByText("Build B")).toBeNull();
    expect(screen.queryByText("Build C")).toBeNull();
    expect(screen.getByLabelText("Stage: testing")).toBeInTheDocument();
  });
});
