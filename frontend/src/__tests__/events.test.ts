import { describe, expect, it } from "vitest";
import type { AgentRun, Iteration, LiveEvent } from "../api/types";
import { eventsFromRuns, initialLive, reduceAll, reduceEvent } from "../lib/events";
import { buildGraph } from "../pages/LiveWorkflow";

const ev = (id: string, event: string, extra: Partial<LiveEvent> = {}): LiveEvent => ({
  id,
  event,
  task_id: "t",
  timestamp: "2026-01-01T00:00:00",
  ...extra,
});

const RUN: LiveEvent[] = [
  ev("1", "task_started"),
  ev("2", "agent_started", { agent: "Planner", iteration: 1 }),
  ev("3", "agent_completed", { agent: "Planner", iteration: 1, status: "success", tokens: 50 }),
  ev("4", "agent_started", { agent: "Verifier", iteration: 1 }),
  ev("5", "tests_completed", { iteration: 1, tests_passed: 3, tests_failed: 1 }),
];

const run = (id: string, agent: string, status: string): AgentRun => ({
  id,
  iteration_id: "i1",
  agent_name: agent,
  input_summary: "",
  output_summary: "",
  status,
  tokens_used: 5,
  duration_seconds: 1,
  error_message: null,
  started_at: "2026-01-01T00:00:00",
});
const iteration = (id: string, number: number) => ({ id, number }) as Iteration;

describe("live reducer", () => {
  it("tracks the current agent, tokens and tests", () => {
    const s = reduceAll(RUN);
    expect(s.current).toBe("Verifier");
    expect(s.agents.Planner).toMatchObject({ state: "success", tokens: 50 });
    expect(s.agents.Verifier.state).toBe("running");
    expect(s.tests).toEqual({ passed: 3, failed: 1 });
    expect(s.iteration).toBe(1);
  });

  it("is idempotent: a replay after reconnect changes nothing", () => {
    const once = reduceAll(RUN);
    const twice = reduceAll(RUN, once);
    expect(twice).toBe(once);
    expect(twice.timeline).toHaveLength(5);
  });

  it("records terminal outcomes and clears them when a new run starts", () => {
    let s = reduceEvent(reduceAll(RUN), ev("6", "task_failed"));
    expect(s.terminal).toBe("FAILED");
    s = reduceEvent(s, ev("7", "task_started"));
    expect(s.terminal).toBeNull();
    expect(reduceEvent(initialLive(), ev("8", "task_completed")).terminal).toBe("COMPLETED");
    expect(reduceEvent(initialLive(), ev("9", "escalated")).terminal).toBe("ESCALATED");
    expect(reduceEvent(initialLive(), ev("10", "task_cancelled")).terminal).toBe("CANCELLED");
  });

  it("marks a failed agent run as failed", () => {
    const s = reduceAll([
      ev("1", "agent_started", { agent: "Builder" }),
      ev("2", "agent_completed", { agent: "Builder", status: "failed" }),
    ]);
    expect(s.agents.Builder.state).toBe("failed");
    expect(s.current).toBeNull();
  });
});

describe("REST fallback", () => {
  it("produces the same ids as the server so a later socket replay is de-duplicated", () => {
    const events = eventsFromRuns("t", [run("r1", "Planner", "success")], [iteration("i1", 1)]);
    expect(events.map((e) => e.id)).toEqual(["run-start:r1", "run-end:r1"]);
    const s = reduceAll(events);
    expect(reduceAll(events, s)).toBe(s);
  });

  it("emits only a start for a still-running agent", () => {
    const events = eventsFromRuns("t", [run("r2", "Verifier", "running")], [iteration("i1", 2)]);
    expect(events.map((e) => e.event)).toEqual(["agent_started"]);
  });
});

describe("agent graph", () => {
  it("has every node and the retry loop, with the current agent highlighted", () => {
    const g = buildGraph(reduceAll(RUN));
    expect(g.nodes.map((n) => n.id).sort()).toEqual(
      ["Builder", "Decision", "Planner", "Repair", "Reviewer", "Verifier"],
    );
    expect(g.edges.map((e) => e.id)).toContain("Repair-Verifier");
    expect(g.nodes.find((n) => n.id === "Verifier")?.className).toContain("running");
    expect(g.nodes.find((n) => n.id === "Planner")?.className).toContain("success");
    expect(g.edges.find((e) => e.id === "Builder-Verifier")?.animated).toBe(true);
  });

  it("shows the Decision Engine green on completion and red otherwise", () => {
    const done = buildGraph(reduceAll([...RUN, ev("6", "task_completed")]));
    expect(done.nodes.find((n) => n.id === "Decision")?.className).toContain("success");
    const bad = buildGraph(reduceAll([...RUN, ev("6", "escalated")]));
    expect(bad.nodes.find((n) => n.id === "Decision")?.className).toContain("failed");
  });
});
