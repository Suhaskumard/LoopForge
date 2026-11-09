import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Explanation, ModelStat, Routing } from "../api/types";
import { ExplainerCard } from "../components/Explainer";
import { RoutingPanel, Scatter } from "../components/Routing";
import { draftProblems } from "../pages/Pipelines";

beforeEach(() => vi.restoreAllMocks());

const explanation: Explanation = {
  summary: "The update endpoint returns the wrong employee every time.",
  root_causes: ["employee_id + 1 is used as the lookup key"],
  suggested_fix: "Look the employee up by the id from the path.",
  retry_note: "Use employee_id as-is in the update handler.",
  confidence: "high",
  source: "ai",
  evidence: ["Stop reason: identical failure twice", "Failing test test_update: 404"],
  iteration: 3,
  created_at: "2026-11-09T10:00:00",
};

describe("failure explainer", () => {
  it("is hidden for tasks that did not fail", () => {
    vi.spyOn(api, "get").mockResolvedValue(null);
    const { container } = render(<ExplainerCard taskId="t" status="COMPLETED" canAct />);
    expect(container.querySelector("[data-testid=explainer]")).toBeNull();
  });

  it("explains on request, then retries with the fix", async () => {
    vi.spyOn(api, "get").mockResolvedValue(null);
    const post = vi.spyOn(api, "post").mockImplementation(async (path: string) =>
      (path.endsWith("/explanation") ? explanation : { id: "t" }) as never,
    );
    const onRetried = vi.fn();
    render(<ExplainerCard taskId="t" status="ESCALATED" canAct onRetried={onRetried} />);
    await userEvent.click(await screen.findByRole("button", { name: "Explain this failure" }));
    expect(await screen.findByText(explanation.summary)).toBeInTheDocument();
    expect(screen.getByText("AI analysis")).toBeInTheDocument();
    expect(screen.getByText("high confidence")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Show the 2 facts/ }));
    expect(screen.getByText("Failing test test_update: 404")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry with this fix" }));
    await waitFor(() => expect(onRetried).toHaveBeenCalled());
    expect(post).toHaveBeenLastCalledWith("/tasks/t/explanation/apply");
  });

  it("viewers can read a stored explanation but not act on it", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ ...explanation, source: "evidence" });
    render(<ExplainerCard taskId="t" status="FAILED" canAct={false} />);
    expect(await screen.findByText("From the evidence")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry with this fix" })).toBeNull();
  });
});

describe("pipeline builder", () => {
  const step = (requirement: string) => ({ requirement, criteria: "", rounds: 5 });
  it("needs a name and 2-10 real steps", () => {
    expect(draftProblems("", [step("Build the API"), step("Add a client")])).toEqual(["Give the pipeline a name."]);
    expect(draftProblems("x", [step("Build the API")])).toContain("A pipeline needs at least 2 steps.");
    expect(draftProblems("x", [step("Build the API"), step("")])).toEqual(["Step 2 needs a requirement."]);
    expect(draftProblems("x", Array.from({ length: 11 }, () => step("Build it")))).toContain("At most 10 steps.");
    expect(draftProblems("x", [step("Build the API"), step("Add a client")])).toEqual([]);
  });
});

describe("model routing", () => {
  const stat = (model: string, rate: number, cost: number): ModelStat => ({
    agent: "Repair", model, runs: 10, tasks: 6, accepted: Math.round(rate * 6), accept_rate: rate, tokens_per_run: 500, cost_per_run: cost,
  });

  it("plots models and highlights the recommended one", () => {
    const { container } = render(<Scatter points={[stat("big", 0.9, 0.05), stat("medium", 0.85, 0.01)]} pick="medium" />);
    expect(container.querySelectorAll("circle")).toHaveLength(2);
    expect(container.querySelectorAll(".rt-pick circle")).toHaveLength(1);
  });

  it("applies a recommendation for one agent", async () => {
    const routing: Routing = {
      routing: {},
      stats: [stat("big", 0.9, 0.05), stat("medium", 0.85, 0.01)],
      recommendations: [{ agent: "Repair", model: "medium", reason: "Accepted 85% of 6 tasks" }],
      window_days: 90,
    };
    vi.spyOn(api, "get").mockResolvedValue(routing);
    const put = vi.spyOn(api, "put").mockResolvedValue(routing);
    render(<MemoryRouter><RoutingPanel orgId="o1" canEdit /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "Apply recommendation" }));
    expect(put).toHaveBeenCalledWith("/orgs/o1/routing", { routing: { Repair: "medium" } });
  });

  it("says when there is no evidence yet", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ routing: {}, stats: [], recommendations: [], window_days: 90 });
    render(<MemoryRouter><RoutingPanel orgId="o1" canEdit={false} /></MemoryRouter>);
    expect(await screen.findByText(/No runs with a recorded model yet/)).toBeInTheDocument();
  });
});
