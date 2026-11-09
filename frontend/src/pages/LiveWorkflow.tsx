import "@xyflow/react/dist/style.css";
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../auth";
import type { Task } from "../api/types";
import { isTerminal } from "../api/types";
import { Approvals } from "../components/Approvals";
import { Confetti } from "../components/Confetti";
import { AgentRoster, ago, glyph, groupByIteration, PacketEdge, Reactor, StageRail, TestsBar, useNow } from "../components/LiveViz";
import { toast } from "../components/Toast";
import { PlanPanel } from "../components/PlanPanel";
import { ReplayBar, useReplay } from "../components/Replay";
import { useTabStatus } from "../lib/tabStatus";
import { TaskTabs } from "../components/Layout";
import { IconFlow } from "../components/icons";
import { Card, Empty, ErrorBox, Kpi, Loading, PageHeader, StatusBadge } from "../components/ui";
import { useAsync, useTaskEvents } from "../hooks";
import { AGENTS, EVENT_LABEL, describe, type LiveState } from "../lib/events";

const POSITIONS: Record<string, { x: number; y: number }> = {
  Planner: { x: 0, y: 0 },
  Builder: { x: 190, y: 0 },
  Verifier: { x: 380, y: 0 },
  Reviewer: { x: 570, y: 0 },
  Decision: { x: 760, y: 0 },
  Repair: { x: 570, y: 130 },
};

const AGENT_GLYPH: Record<string, string> = {
  Planner: "M4 6h16M4 12h10M4 18h6",
  Builder: "M8 8l-5 4 5 4M16 8l5 4-5 4M14 5l-4 14",
  Verifier: "M5 12l4 4L19 7",
  Reviewer: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 100 6 3 3 0 000-6z",
  Decision: "M12 3v6m0 0l-6 6m6-6l6 6M6 21h.01M18 21h.01",
  Repair: "M14 6a4 4 0 00-5 5L3 17l4 4 6-6a4 4 0 005-5l-3 3-3-3z",
};

/** Custom node: icon + name + state chip. The wrapper's className (flow-node <state>) still carries the state. */
function AgentNode({ id, data }: NodeProps) {
  const label = String((data as { label: string }).label);
  return (
    <div className="agent-node">
      <Handle type="target" position={Position.Left} />
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={AGENT_GLYPH[id] ?? AGENT_GLYPH.Planner} />
      </svg>
      <span>{label}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { agent: AgentNode };
const edgeTypes = { packet: PacketEdge };

export function buildGraph(live: LiveState): { nodes: Node[]; edges: Edge[] } {
  const decisionState =
    live.terminal === "COMPLETED" ? "success" : live.terminal ? "failed" : "idle";
  const nodes: Node[] = [...AGENTS, "Decision"].map((name) => {
    const state = name === "Decision" ? decisionState : (live.agents[name]?.state ?? "idle");
    const iteration = name === "Decision" ? null : live.agents[name]?.iteration;
    return {
      id: name,
      position: POSITIONS[name],
      type: "agent",
      draggable: false,
      selectable: false,
      data: { label: name === "Decision" ? "Decision Engine" : `${name}${iteration ? ` · it.${iteration}` : ""}` },
      className: `flow-node ${state}`,
    };
  });
  const edge = (a: string, b: string, label?: string): Edge => ({
    id: `${a}-${b}`,
    source: a,
    target: b,
    type: "packet",
    label,
    animated: live.current === a || live.current === b,
  });
  return {
    nodes,
    edges: [
      edge("Planner", "Builder"),
      edge("Builder", "Verifier"),
      edge("Verifier", "Reviewer"),
      edge("Reviewer", "Decision"),
      edge("Decision", "Repair", "retry"),
      edge("Repair", "Verifier", "re-run"),
    ],
  };
}

/** Screen 3 — Live Workflow: agent graph, current agent/iteration, status and event timeline. */
export function LiveWorkflow() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const task = useAsync(() => api.get<Task>(`/tasks/${id}`), [id]);
  const { live, connection, reconnect } = useTaskEvents(id);
  const [actionError, setActionError] = useState<string>();
  const replay = useReplay(live.timeline);
  const view = replay.state ?? live; // during a replay every panel shows the historical state
  const graph = useMemo(() => buildGraph(view), [view]);
  const now = useNow(!live.terminal && live.timeline.length > 0); // keeps "12s ago" fresh while running

  // The task row is the authority for status; refresh it whenever the stream says something changed.
  const lastEvent = live.timeline.length;
  useAsyncRefresh(task.reload, lastEvent);

  const t = task.data;
  const lastAt = lastStamp(live.timeline);
  const stalled =
    !!t && !isTerminal(t.status) && !["PENDING", "AWAITING_APPROVAL"].includes(t.status) &&
    !live.terminal && lastAt !== undefined && now - lastAt > STALL_MS;
  const tabState = !t ? null : t.status === "COMPLETED" ? "ok" : ["FAILED", "ESCALATED"].includes(t.status) ? "bad" : isTerminal(t.status) || t.status === "PENDING" ? null : "running";
  useTabStatus(tabState, tabState === "running" ? (live.current ?? "Running") : tabState === "ok" ? "Accepted" : "Needs attention");
  const act = async (...paths: string[]) => {
    setActionError(undefined);
    try {
      for (const path of paths) await api.post(`/tasks/${id}/${path}`);
      toast(
        paths.includes("cancel") ? "Task cancelled" : paths.includes("retry") ? "Retrying — the loop is back on" : paths.includes("resume") ? "Resumed from the last checkpoint" : "Loop started",
        paths.includes("cancel") ? "info" : "ok",
      );
      task.reload();
      if (!paths.includes("cancel")) reconnect(); // a new run: re-subscribe from the replayed history
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed");
      toast(e instanceof Error ? e.message : "Action failed", "bad");
    }
  };

  return (
    <>
      <PageHeader icon={<IconFlow />} title="Live Workflow" sub={t && <p className="clip">{t.requirement}</p>}>
          <span className={`conn ${connection}`} data-testid="connection">{connection}</span>
          {t && <StatusBadge status={t.status} />}
          {can("developer") && t?.status === "PENDING" && <button className="primary" onClick={() => void act("start")}>Start</button>}
          {can("developer") && t && ["FAILED", "ESCALATED"].includes(t.status) && (
            <button onClick={() => void act("retry", "start")}>Retry</button>
          )}
          {can("developer") && t && stalled && (
            <button className="primary" title="No progress for a while: continue from the last checkpoint" onClick={() => void act("resume")}>Resume</button>
          )}
          {can("developer") && t && !isTerminal(t.status) && t.status !== "PENDING" && <button onClick={() => void act("cancel")}>Cancel</button>}
      </PageHeader>
      <TaskTabs id={id} />
      {t?.status === "AWAITING_APPROVAL" && (
        <Approvals taskId={id} signal={live.timeline.length} canDecide={can("approver")} onDecided={() => { task.reload(); reconnect(); }} />
      )}
      {task.error && <ErrorBox error={task.error} />}
      {actionError && <p className="error" role="alert">{actionError}</p>}
      {!t && task.loading && <Loading />}

      {stalled && (
        <p className="stall-note" role="status">
          No progress for over {Math.round(STALL_MS / 1000)}s. If the server restarted, <b>Resume</b> continues this run from its last checkpoint.
        </p>
      )}
      {live.terminal && live.timeline.length > 1 && <ReplayBar replay={replay} events={live.timeline} />}
      <Reactor live={view} maxIterations={t?.max_iterations ?? 0} status={t?.status} asOf={replay.active ? lastStamp(view.timeline) : undefined} />
      <StageRail live={view} />
      <PlanPanel taskId={id} signal={live.timeline.length} />

      <div className="kpis">
        <Kpi label="Iteration" value={t ? `${Math.max(view.iteration, t.current_iteration)} / ${t.max_iterations}` : "—"} />
        <Kpi label="Current agent" value={view.current ?? (view.terminal ? "—" : "waiting")} />
        <Kpi
          label="Tests (latest)"
          value={view.tests ? `${view.tests.passed} passed · ${view.tests.failed} failed` : "—"}
          hint={view.tests ? <TestsBar passed={view.tests.passed} failed={view.tests.failed} /> : undefined}
        />
        <Kpi
          label="Outcome"
          value={view.terminal ?? "in progress"}
          className={view.terminal === "COMPLETED" ? "win" : view.terminal ? "shake" : ""}
        />
      </div>

      {view.terminal === "COMPLETED" && <Confetti />}
      <div className="lw-grid">
      <Card title="Agent graph" actions={view.current && <span className="badge live-run">{view.current} running</span>}>
        <div className={`flow${view.current ? " active" : ""}`} data-testid="flow">
          <ReactFlow
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            nodes={graph.nodes}
            edges={graph.edges}
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            zoomOnScroll={false}
            proOptions={{ hideAttribution: true }}
          >
            <Background />
          </ReactFlow>
        </div>
      </Card>
      <Card title="Agents">
        <AgentRoster live={view} />
      </Card>
      </div>

      <Card title="Execution timeline" actions={view.timeline.length > 0 && <span className="muted small">{view.timeline.length} events</span>}>
        {view.timeline.length === 0 ? (
          <Empty>{t?.status === "PENDING" ? "Not started yet." : "Waiting for events…"}</Empty>
        ) : (
          <ol className={`timeline${view.terminal ? "" : " running"}`} data-testid="timeline">
            {groupByIteration(view.timeline).flatMap((g, gi) => [
              <li key={`h${gi}`} className="tl-head" aria-hidden="true">
                {g.iteration ? `Iteration ${g.iteration}` : "Setup"}
              </li>,
              ...g.events.map((e) => (
                <li key={e.id} className={`ev ${e.event}`}>
                  <time title={e.timestamp ? new Date(e.timestamp).toLocaleString() : undefined}>
                    {e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ""}
                    <small>{e.timestamp ? ago(e.timestamp, now) : ""}</small>
                  </time>
                  <strong><span className="tl-glyph" aria-hidden="true">{glyph(e)}</span>{EVENT_LABEL[e.event] ?? e.event}</strong>
                  <span className="muted">{describe(e)}</span>
                </li>
              )),
            ])}
          </ol>
        )}
      </Card>
    </>
  );
}


const STALL_MS = 90_000;

/** Timestamp (ms) of the newest event, if any. */
export function lastStamp(timeline: { timestamp: string }[]): number | undefined {
  const t = timeline.length ? Date.parse(timeline[timeline.length - 1].timestamp) : NaN;
  return Number.isNaN(t) ? undefined : t;
}

function useAsyncRefresh(reload: () => void, signal: number) {
  useEffect(() => {
    if (signal > 0) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signal]);
}
