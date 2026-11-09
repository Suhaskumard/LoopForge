import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Forecast, Variant } from "../api/types";
import { budgetRisk, ForecastBlock, verdict, WatchCard } from "../components/Intel";
import { CodeView } from "../components/ui";
import { CreateTask } from "../pages/CreateTask";

beforeEach(() => vi.restoreAllMocks());

const forecast: Forecast = {
  basis: 6, scope: "similar", accept_rate: 0.5,
  tokens: { p50: 12000, p90: 20000 }, cost: { p50: 0.024, p90: 0.04 },
  iterations: { p50: 2, p90: 4 }, seconds: { p50: 95, p90: 300 },
};

describe("forecast", () => {
  it("flags budgets below what half of similar tasks needed", () => {
    expect(budgetRisk(forecast, 10000, null)).toEqual({ tokens: true, cost: false });
    expect(budgetRisk(forecast, 15000, 0.01)).toEqual({ tokens: false, cost: true });
    expect(budgetRisk(forecast, null, null)).toEqual({ tokens: false, cost: false });
    expect(budgetRisk(null, 1, 1)).toEqual({ tokens: false, cost: false });
  });

  it("shows the forecast and warns when the budget is too small", async () => {
    vi.spyOn(api, "get").mockResolvedValue(forecast);
    render(<ForecastBlock language="python" words={20} tokenBudget={5000} maxCost={null} />);
    const block = await screen.findByTestId("forecast", undefined, { timeout: 2000 });
    expect(block).toHaveTextContent("12,000");
    expect(block).toHaveTextContent("50% were accepted");
    expect(block).toHaveTextContent(/likely stop on budget/);
  });
});

describe("A/B verdict", () => {
  const v = (over: Partial<Variant>): Variant => ({
    task_id: "x", status: "COMPLETED", model_overrides: { Repair: "m" }, iterations: 2, tokens: 1000,
    cost: 0.002, quality: 80, seconds: 60, rerun_of: "o", ...over,
  });

  it("picks per-metric winners and an overall winner", () => {
    const r = verdict([v({ quality: 90, tokens: 1500 }), v({ quality: 70, tokens: 900, cost: 0.001 })]);
    expect(r.metric.quality).toBe(0);
    expect(r.metric.tokens).toBe(1);
    expect(r.metric.cost).toBe(1);
    expect(r.metric.iterations).toBeNull(); // tie
    expect(r.overall).toBe(1); // 2 wins vs 1
  });

  it("an accepted run beats a failed one whatever the numbers", () => {
    const r = verdict([v({ status: "FAILED", tokens: 10 }), v({ tokens: 99999 })]);
    expect(r.overall).toBe(1);
  });
});

describe("line notes", () => {
  it("clicking a line number lets you leave a note, shown inline as text", async () => {
    const onNote = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<CodeView content={"a = 1\nb = 2"} path="x.py" notes={[]} onNote={onNote} />);
    await userEvent.click(screen.getByRole("button", { name: "Comment on line 2" }));
    await userEvent.type(screen.getByLabelText("Note for line 2"), "<b>use</b> a constant");
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(onNote).toHaveBeenCalledWith(2, "<b>use</b> a constant");
    rerender(
      <CodeView content={"a = 1\nb = 2"} path="x.py" notes={[{ id: "n", line: 2, body: "<b>use</b> a constant", author: "me@x.com", resolved: false }]} onNote={onNote} />,
    );
    expect(screen.getByText("<b>use</b> a constant")).toBeInTheDocument();
    expect(screen.getByTestId("code").querySelector("b:not(:first-child)")).toBeNull();
  });

  it("read-only viewers see plain line numbers", () => {
    render(<CodeView content={"a = 1"} path="x.py" />);
    expect(screen.queryByRole("button", { name: /Comment on line/ })).toBeNull();
  });
});

describe("regression watch card", () => {
  it("turns the watch on and shows the last result", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ watch: null, reruns: [] });
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    const post = vi.spyOn(api, "post").mockResolvedValue({});
    render(<MemoryRouter><WatchCard taskId="t1" status="COMPLETED" canEdit /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "Daily" }));
    expect(put).toHaveBeenCalledWith("/tasks/t1/watch", { interval_hours: 24, active: true });
    get.mockResolvedValue({
      watch: { task_id: "t1", interval_hours: 24, next_run_at: "2026-11-10T00:00:00", last_run_task_id: "r", last_result: "regressed", active: true },
      reruns: [{ id: "r", status: "FAILED", created_at: "2026-11-09T00:00:00", experiment: null }],
    });
    await userEvent.click(screen.getByRole("button", { name: "Re-run now" }));
    expect(post).toHaveBeenCalledWith("/tasks/t1/rerun");
    expect(await screen.findByTestId("watch-result")).toHaveTextContent("regressed");
  });

  it("explains itself for tasks that are not accepted yet", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ watch: null, reruns: [] });
    vi.spyOn(api, "post").mockResolvedValue({});
    render(<MemoryRouter><WatchCard taskId="t1" status="FAILED" canEdit /></MemoryRouter>);
    expect(await screen.findByText(/Once this task is accepted/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-run now" })).toBeNull();
  });
});

describe("task chains", () => {
  it("?from=<id> continues that task inside its own project", async () => {
    vi.spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/tasks/src1") return { id: "src1", project_id: "p9", status: "COMPLETED" } as never;
      if (path === "/tasks") return [{ id: "src1", project_id: "p9", status: "COMPLETED", requirement: "Base API", current_iteration: 2 }] as never;
      return [] as never;
    });
    const post = vi.spyOn(api, "post").mockImplementation(async () => ({ id: "t2" }) as never);
    render(
      <MemoryRouter initialEntries={["/tasks/new?from=src1"]}>
        <Routes><Route path="/tasks/new" element={<CreateTask />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Continuing from")).toBeInTheDocument(); // the picker shows the chosen task
    await userEvent.click(screen.getByRole("button", { name: /Create and start/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tasks/t2/start"));
    expect(post.mock.calls.some((c) => c[0] === "/projects")).toBe(false);
    const body = post.mock.calls.find((c) => c[0] === "/tasks")![1] as Record<string, unknown>;
    expect(body).toMatchObject({ project_id: "p9", source_type: "task", from_task_id: "src1" });
  });
});
