import "@xyflow/react/dist/style.css";
import { Background, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../auth";
import type { Task } from "../api/types";
import { isTerminal } from "../api/types";
import { Approvals } from "../components/Approvals";
import { TaskTabs } from "../components/Layout";
import { Card, Empty, ErrorBox, Kpi, Loading, StatusBadge } from "../components/ui";
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

export function buildGraph(live: LiveState): { nodes: Node[]; edges: Edge[] } {
  const decisionState =
    live.terminal === "COMPLETED" ? "success" : live.terminal ? "failed" : "idle";
  const nodes: Node[] = [...AGENTS, "Decision"].map((name) => {
    const state = name === "Decision" ? decisionState : (live.agents[name]?.state ?? "idle");
    const iteration = name === "Decision" ? null : live.agents[name]?.iteration;
    return {
      id: name,
      position: POSITIONS[name],
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
  const graph = useMemo(() => buildGraph(live), [live]);

  // The task row is the authority for status; refresh it whenever the stream says something changed.
  const lastEvent = live.timeline.length;
  useAsyncRefresh(task.reload, lastEvent);

  const t = task.data;
  const act = async (...paths: string[]) => {
    setActionError(undefined);
    try {
      for (const path of paths) await api.post(`/tasks/${id}/${path}`);
      task.reload();
      if (!paths.includes("cancel")) reconnect(); // a new run: re-subscribe from the replayed history
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed");
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Live Workflow</h1>
          {t && <p className="muted clip">{t.requirement}</p>}
        </div>
        <div className="row">
          <span className={`conn ${connection}`} data-testid="connection">{connection}</span>
          {t && <StatusBadge status={t.status} />}
          {can("developer") && t?.status === "PENDING" && <button className="primary" onClick={() => void act("start")}>Start</button>}
          {can("developer") && t && ["FAILED", "ESCALATED"].includes(t.status) && (
            <button onClick={() => void act("retry", "start")}>Retry</button>
          )}
          {can("developer") && t && !isTerminal(t.status) && t.status !== "PENDING" && <button onClick={() => void act("cancel")}>Cancel</button>}
        </div>
      </header>
      <TaskTabs id={id} />
      {t?.status === "AWAITING_APPROVAL" && (
        <Approvals taskId={id} signal={live.timeline.length} canDecide={can("approver")} onDecided={() => { task.reload(); reconnect(); }} />
      )}
      {task.error && <ErrorBox error={task.error} />}
      {actionError && <p className="error" role="alert">{actionError}</p>}
      {!t && task.loading && <Loading />}

      <div className="kpis">
        <Kpi label="Iteration" value={t ? `${Math.max(live.iteration, t.current_iteration)} / ${t.max_iterations}` : "—"} />
        <Kpi label="Current agent" value={live.current ?? (live.terminal ? "—" : "waiting")} />
        <Kpi label="Tests (latest)" value={live.tests ? `${live.tests.passed} passed · ${live.tests.failed} failed` : "—"} />
        <Kpi label="Outcome" value={live.terminal ?? "in progress"} />
      </div>

      <Card title="Agent graph">
        <div className="flow" data-testid="flow">
          <ReactFlow
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

      <Card title="Execution timeline">
        {live.timeline.length === 0 ? (
          <Empty>{t?.status === "PENDING" ? "Not started yet." : "Waiting for events…"}</Empty>
        ) : (
          <ol className="timeline" data-testid="timeline">
            {live.timeline.map((e) => (
              <li key={e.id} className={`ev ${e.event}`}>
                <time>{e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ""}</time>
                <strong>{EVENT_LABEL[e.event] ?? e.event}</strong>
                <span className="muted">{describe(e)}</span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </>
  );
}


function useAsyncRefresh(reload: () => void, signal: number) {
  useEffect(() => {
    if (signal > 0) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signal]);
}
