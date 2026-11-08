import type { AgentRun, Iteration, LiveEvent } from "../api/types";

export const AGENTS = ["Planner", "Builder", "Verifier", "Reviewer", "Repair"] as const; // graph nodes; Documentation runs after the verdict and appears in the timeline only
export type AgentName = (typeof AGENTS)[number];

export type AgentState = "idle" | "running" | "success" | "failed";

export interface LiveState {
  seen: Record<string, true>;
  timeline: LiveEvent[];
  agents: Record<string, { state: AgentState; iteration: number | null; tokens: number }>;
  current: string | null;
  iteration: number;
  terminal: string | null;
  tests: { passed: number; failed: number } | null;
}

const TERMINAL_EVENTS: Record<string, string> = {
  task_completed: "COMPLETED",
  task_cancelled: "CANCELLED",
  escalated: "ESCALATED",
  task_failed: "FAILED",
};

export function initialLive(): LiveState {
  return {
    seen: {},
    timeline: [],
    agents: Object.fromEntries(AGENTS.map((a) => [a, { state: "idle", iteration: null, tokens: 0 }])),
    current: null,
    iteration: 0,
    terminal: null,
    tests: null,
  };
}

/** Fold one event into the view state. Idempotent: replays and reconnects never double-apply. */
export function reduceEvent(state: LiveState, e: LiveEvent): LiveState {
  if (state.seen[e.id]) return state;
  const next: LiveState = {
    ...state,
    seen: { ...state.seen, [e.id]: true },
    timeline: [...state.timeline, e],
    agents: { ...state.agents },
  };
  if (typeof e.iteration === "number") next.iteration = Math.max(next.iteration, e.iteration);
  switch (e.event) {
    case "task_started":
      // A retried task starts a fresh run: forget the previous run's terminal state.
      next.terminal = null;
      break;
    case "agent_started":
      if (e.agent) {
        next.agents[e.agent] = { state: "running", iteration: e.iteration ?? null, tokens: next.agents[e.agent]?.tokens ?? 0 };
        next.current = e.agent;
      }
      break;
    case "agent_completed":
      if (e.agent) {
        const prev = next.agents[e.agent];
        next.agents[e.agent] = {
          state: e.status === "success" ? "success" : "failed",
          iteration: e.iteration ?? null,
          tokens: (prev?.tokens ?? 0) + (e.tokens ?? 0),
        };
        if (next.current === e.agent) next.current = null;
      }
      break;
    case "tests_completed":
      next.tests = { passed: e.tests_passed ?? 0, failed: e.tests_failed ?? 0 };
      break;
    default:
      if (TERMINAL_EVENTS[e.event]) {
        next.terminal = TERMINAL_EVENTS[e.event];
        next.current = null;
      }
  }
  return next;
}

export function reduceAll(events: LiveEvent[], from: LiveState = initialLive()): LiveState {
  return events.reduce(reduceEvent, from);
}

/**
 * REST fallback: derive the same events from /agent-runs (ids match the server's, so a later
 * WebSocket replay is de-duplicated). `numbers` maps iteration id -> iteration number.
 */
export function eventsFromRuns(taskId: string, runs: AgentRun[], iterations: Iteration[]): LiveEvent[] {
  const numbers = new Map(iterations.map((i) => [i.id, i.number]));
  const out: LiveEvent[] = [];
  for (const r of runs) {
    const iteration = numbers.get(r.iteration_id) ?? null;
    out.push({
      id: `run-start:${r.id}`,
      event: "agent_started",
      task_id: taskId,
      timestamp: r.started_at,
      agent: r.agent_name,
      iteration,
    });
    if (r.status !== "running") {
      out.push({
        id: `run-end:${r.id}`,
        event: "agent_completed",
        task_id: taskId,
        timestamp: r.started_at,
        agent: r.agent_name,
        iteration,
        status: r.status,
        tokens: r.tokens_used,
        duration_seconds: r.duration_seconds,
      });
    }
  }
  return out;
}

export const EVENT_LABEL: Record<string, string> = {
  task_started: "Task started",
  agent_started: "Agent started",
  agent_completed: "Agent finished",
  sandbox_started: "Sandbox started",
  tests_completed: "Tests completed",
  iteration_completed: "Iteration verdict",
  retry_scheduled: "Repair scheduled",
  approval_requested: "Waiting for your approval",
  approval_decided: "Approval decision",
  escalated: "Escalated to a human",
  task_completed: "Task completed",
  task_cancelled: "Task cancelled",
  task_failed: "Task failed",
};

export function describe(e: LiveEvent): string {
  switch (e.event) {
    case "agent_started":
    case "agent_completed":
      return `${e.agent}${e.iteration ? ` · iteration ${e.iteration}` : ""}${e.status && e.event === "agent_completed" ? ` · ${e.status}` : ""}`;
    case "tests_completed":
      return `iteration ${e.iteration}: ${e.tests_passed} passed, ${e.tests_failed} failed`;
    case "iteration_completed":
      return `iteration ${e.iteration}: ${e.status} (${e.tests_passed} passed, ${e.tests_failed} failed)`;
    case "approval_requested":
    case "approval_decided":
      return `${e.kind ?? ""}${e.decision ? ` · ${e.decision}` : ""}`;
    case "retry_scheduled":
      return `iteration ${e.iteration}${e.files?.length ? ` · ${e.files.join(", ")}` : ""}`;
    default:
      return e.iteration ? `iteration ${e.iteration}` : "";
  }
}
