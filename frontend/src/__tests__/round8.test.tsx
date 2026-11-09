import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { api } from "../api/client";
import type { GraphEdge, GraphNode, LiveEvent, RepairRecord } from "../api/types";
import { Integrations } from "../components/Integrations";
import { foldTo } from "../components/Replay";
import { forceLayout } from "../lib/forceLayout";
import { adjacency, neighbourhood, search, shortestPath } from "../lib/graphQuery";
import { forecast, rankSimilar, terms } from "../lib/similarity";
import { lastStamp } from "../pages/LiveWorkflow";
import { summarize } from "../pages/Lessons";

beforeEach(() => vi.restoreAllMocks());

const node = (id: string, type: GraphNode["type"], label: string, status: string | null = null): GraphNode => ({ id, type, label, status, meta: {} });
const edge = (source: string, target: string, kind: GraphEdge["kind"] = "contains"): GraphEdge => ({ source, target, kind });

describe("force layout", () => {
  const nodes = ["p", "a", "b", "c", "f"].map((id) => ({ id, weight: id === "p" ? 4 : 1 }));
  const edges = [{ source: "p", target: "a" }, { source: "p", target: "b" }, { source: "p", target: "c" }, { source: "a", target: "f" }];

  it("is deterministic and stays inside its box", () => {
    const one = forceLayout(nodes, edges, { spread: 800 });
    expect(forceLayout(nodes, edges, { spread: 800 })).toEqual(one);
    for (const p of Object.values(one)) {
      expect(Math.abs(p.x)).toBeLessThanOrEqual(400);
      expect(Math.abs(p.y)).toBeLessThanOrEqual(400);
    }
  });

  it("keeps nodes apart and linked nodes closer than unlinked ones", () => {
    const pos = forceLayout(nodes, edges);
    const d = (a: string, b: string) => Math.hypot(pos[a].x - pos[b].x, pos[a].y - pos[b].y);
    expect(d("a", "b")).toBeGreaterThan(5);
    expect(d("a", "f")).toBeLessThan(d("b", "f"));
    expect(forceLayout([], [])).toEqual({});
  });
});

describe("graph queries", () => {
  const nodes = [
    node("p:1", "project", "slug utils"),
    node("t:1", "task", "Write a slugify function", "COMPLETED"),
    node("t:2", "task", "Build a todo API", "FAILED"),
    node("f:import", "failure", "import"),
    node("x:1", "task", "Lonely task"),
  ];
  const adj = adjacency([edge("p:1", "t:1"), edge("p:1", "t:2"), edge("t:2", "f:import", "failed_with")]);

  it("ranks exact and prefix matches first, and matches status words", () => {
    expect(search(nodes, "import")[0].id).toBe("f:import");
    expect(search(nodes, "slug").map((n) => n.id)).toEqual(["p:1", "t:1"]);
    expect(search(nodes, "failed").map((n) => n.id)).toEqual(["t:2"]);
    expect(search(nodes, "  ")).toEqual([]);
  });

  it("finds neighbours and the shortest path, or none when disconnected", () => {
    expect([...neighbourhood("p:1", adj)].sort()).toEqual(["p:1", "t:1", "t:2"]);
    expect(shortestPath("t:1", "f:import", adj)).toEqual(["t:1", "p:1", "t:2", "f:import"]);
    expect(shortestPath("t:1", "x:1", adj)).toEqual([]);
  });
});

describe("similar tasks", () => {
  const docs = [
    { item: { id: "a", status: "COMPLETED", current_iteration: 2 }, text: "Build a FastAPI URL shortener with redirect endpoints and tests" },
    { item: { id: "b", status: "FAILED", current_iteration: 5 }, text: "URL shortener service with analytics and tests" },
    { item: { id: "c", status: "COMPLETED", current_iteration: 1 }, text: "CSV statistics command line tool" },
  ];

  it("stems words, ranks by overlap and ignores unrelated tasks", () => {
    expect(terms("Tests for the endpoints")).toEqual(["test", "endpoint"]);
    const r = rankSimilar("a URL shortener API with redirects and tests", docs);
    expect(r.map((x) => x.item.id)).toEqual(["a", "b"]);
    expect(rankSimilar("hi", docs)).toEqual([]);
  });

  it("forecasts from finished similar tasks", () => {
    expect(forecast(docs.map((d) => d.item))).toEqual({ basis: 3, acceptRate: 2 / 3, avgIterations: 1.5 });
    expect(forecast([{ status: "TESTING", current_iteration: 1 }])).toEqual({ basis: 0, acceptRate: null, avgIterations: null });
  });
});

describe("lessons and replay", () => {
  const rec = (failure_class: string, outcome: string, task_id: string, learnable = true): RepairRecord => ({
    id: `${task_id}-${failure_class}-${outcome}`, task_id, task_requirement: "r", task_status: "COMPLETED", learnable, failure_class,
    failure_category: "", fingerprint: null, root_cause: "", proposed_fix: "", files_modified: [], outcome,
    regression_status: "", tokens_used: 100, duration_seconds: 1, created_at: "2026-11-09T10:00:00",
  });

  it("groups repairs into classes, busiest first", () => {
    const s = summarize([rec("import", "resolved", "a"), rec("import", "unresolved", "b"), rec("assertion", "resolved", "a", false)]);
    expect(s.map((c) => [c.name, c.total, c.resolved, c.tasks, c.reusable])).toEqual([
      ["import", 2, 1, 2, 1],
      ["assertion", 1, 1, 1, 0],
    ]);
  });

  it("replay folds the history up to the cursor", () => {
    const ev = (id: string, event: string, extra: Partial<LiveEvent> = {}): LiveEvent => ({ id, event, task_id: "t", timestamp: `2026-11-09T10:00:0${id}Z`, ...extra });
    const events = [ev("1", "agent_started", { agent: "Planner", iteration: 1 }), ev("2", "agent_completed", { agent: "Planner", iteration: 1, status: "success" }), ev("3", "task_completed")];
    expect(foldTo(events, 1).current).toBe("Planner");
    expect(foldTo(events, 2).agents.Planner.state).toBe("success");
    expect(foldTo(events, 2).terminal).toBeNull();
    expect(foldTo(events, 3).terminal).toBe("COMPLETED");
    expect(foldTo(events, 0).timeline).toHaveLength(0);
    expect(lastStamp(events)).toBe(Date.parse("2026-11-09T10:00:03Z"));
    expect(lastStamp([])).toBeUndefined();
  });
});

describe("integrations", () => {
  it("shows a new webhook's signing secret exactly once", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue([]);
    vi.spyOn(api, "post").mockResolvedValue({ id: "w1", url: "https://example.com/hook", events: [], format: "json", active: true, created_at: "x", secret: "whsec_123" });
    render(<Integrations orgId="o1" />);
    await waitFor(() => expect(get).toHaveBeenCalledWith("/orgs/o1/webhooks"));
    await userEvent.type(screen.getByLabelText("Endpoint URL"), "https://example.com/hook");
    await userEvent.click(screen.getByRole("button", { name: "Add webhook" }));
    expect(await screen.findByTestId("one-time-secret")).toHaveTextContent("whsec_123");
    await act(() => userEvent.click(screen.getByRole("button", { name: /stored it/ })));
    expect(screen.queryByTestId("one-time-secret")).toBeNull();
  });
});
