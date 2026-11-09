import "@xyflow/react/dist/style.css";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { GraphNode, GraphNodeType, WorkspaceGraph } from "../api/types";
import { isTerminal } from "../api/types";
import { IconGraph } from "../components/icons";
import { Empty, ErrorBox, PageHeader, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";
import { forceLayout } from "../lib/forceLayout";
import { adjacency, neighbourhood, pathEdges, search, shortestPath } from "../lib/graphQuery";

const TYPES: { id: GraphNodeType; label: string }[] = [
  { id: "project", label: "Projects" },
  { id: "task", label: "Tasks" },
  { id: "failure", label: "Failures" },
  { id: "file", label: "Files" },
];
const EDGE_LEN: Record<string, number> = { contains: 90, failed_with: 150, touched: 130, learned_from: 170, chained_from: 120, rerun_of: 80 };
const WEIGHT: Record<GraphNodeType, number> = { project: 4, failure: 2, task: 1, file: 0.8 };

type Mood = "running" | "ok" | "bad" | "idle";
export const moodOf = (n: GraphNode): Mood =>
  n.type !== "task" ? "idle" : n.status === "COMPLETED" ? "ok" : n.status && ["FAILED", "ESCALATED"].includes(n.status) ? "bad" : n.status && !isTerminal(n.status) && n.status !== "PENDING" ? "running" : "idle";

interface OrbData extends Record<string, unknown> {
  node: GraphNode;
  state: "" | "dim" | "hl" | "sel" | "path";
}

function Orb({ data }: NodeProps) {
  const { node, state } = data as OrbData;
  const count = Number(node.meta.count ?? node.meta.tasks ?? node.meta.repairs ?? 0);
  return (
    <div className={`orb orb-${node.type} mood-${moodOf(node)} ${state}`} title={node.label}>
      <Handle type="target" position={Position.Top} />
      <span className="orb-core" style={node.type === "failure" ? { transform: `scale(${Math.min(1.8, 1 + count * 0.12)})` } : undefined}>
        {node.type === "project" ? node.label.slice(0, 1).toUpperCase() : node.type === "failure" ? "!" : ""}
      </span>
      <span className="orb-label">{node.label}</span>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
const nodeTypes = { orb: Orb };

export function TaskGraph() {
  return (
    <ReactFlowProvider>
      <GraphView />
    </ReactFlowProvider>
  );
}

function GraphView() {
  const graph = useAsync(() => api.get<WorkspaceGraph>("/graph"), []);
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [types, setTypes] = useState<Set<GraphNodeType>>(() => {
    const t = params.get("types");
    return new Set((t ? t.split(",") : TYPES.map((x) => x.id)) as GraphNodeType[]);
  });
  const [selected, setSelected] = useState<string | null>(params.get("focus"));
  const [hovered, setHovered] = useState<string | null>(null);
  const [pathFrom, setPathFrom] = useState<string | null>(null);
  const [path, setPath] = useState<string[]>([]);
  const flow = useReactFlow();
  const searchBox = useRef<HTMLInputElement>(null);

  const data = graph.data;
  const visible = useMemo(() => (data?.nodes ?? []).filter((n) => types.has(n.type)), [data, types]);
  const visibleIds = useMemo(() => new Set(visible.map((n) => n.id)), [visible]);
  const visibleEdges = useMemo(
    () => (data?.edges ?? []).filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)),
    [data, visibleIds],
  );
  const adj = useMemo(() => adjacency(visibleEdges), [visibleEdges]);
  const positions = useMemo(
    () =>
      forceLayout(
        visible.map((n) => ({ id: n.id, weight: WEIGHT[n.type] })),
        visibleEdges.map((e) => ({ source: e.source, target: e.target, length: EDGE_LEN[e.kind] })),
      ),
    [visible, visibleEdges],
  );
  const matches = useMemo(() => search(visible, query), [visible, query]);
  const matchIds = useMemo(() => new Set(matches.map((m) => m.id)), [matches]);
  const focus = hovered ?? selected;
  const around = useMemo(() => (focus ? neighbourhood(focus, adj) : null), [focus, adj]);
  const onPath = useMemo(() => new Set(path), [path]);
  const pathKeys = useMemo(() => pathEdges(path), [path]);

  // keep shareable state in the URL
  useEffect(() => {
    const next = new URLSearchParams();
    if (query) next.set("q", query);
    if (selected) next.set("focus", selected);
    if (types.size !== TYPES.length) next.set("types", [...types].join(","));
    setParams(next, { replace: true });
  }, [query, selected, types, setParams]);

  // "/" focuses the query bar
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key === "/" && !t?.closest?.("input, textarea, select")) {
        e.preventDefault();
        searchBox.current?.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  const nodes: Node[] = visible.map((n) => {
    let state: OrbData["state"] = "";
    if (path.length) state = onPath.has(n.id) ? "path" : "dim";
    else if (n.id === selected) state = "sel";
    else if (query && matches.length) state = matchIds.has(n.id) ? "hl" : "dim";
    else if (around) state = around.has(n.id) ? "hl" : "dim";
    return {
      id: n.id,
      type: "orb",
      position: positions[n.id] ?? { x: 0, y: 0 },
      data: { node: n, state } satisfies OrbData,
      draggable: true,
      selectable: false,
    };
  });
  const edges: Edge[] = visibleEdges.map((e) => {
    const key = `${e.source}|${e.target}`;
    const lit = path.length ? pathKeys.has(key) : !!around && around.has(e.source) && around.has(e.target) && (e.source === focus || e.target === focus);
    const dim = (path.length && !lit) || (!!around && !lit && !path.length);
    return {
      id: `${e.kind}:${key}`,
      source: e.source,
      target: e.target,
      type: "straight",
      animated: e.kind === "learned_from" || e.kind === "chained_from" || lit,
      markerEnd: e.kind === "chained_from" ? { type: MarkerType.ArrowClosed, color: "#38d5f5", width: 16, height: 16 } : undefined,
      className: `gedge k-${e.kind}${lit ? " lit" : ""}${dim ? " dim" : ""}`,
    };
  });

  const flyTo = (id: string) => {
    const p = positions[id];
    if (p) void flow.setCenter(p.x, p.y, { zoom: 1.3, duration: 650 });
    setSelected(id);
  };
  const pick = (id: string) => {
    if (pathFrom) {
      const found = shortestPath(pathFrom, id, adj);
      setPath(found);
      setPathFrom(null);
      setSelected(id);
      return;
    }
    setPath([]);
    setSelected(id === selected ? null : id);
  };
  const toggleType = (t: GraphNodeType) =>
    setTypes((cur) => {
      const next = new Set(cur);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next.size ? next : cur;
    });

  const byId = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);
  const sel = selected ? byId.get(selected) : undefined;
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const n of data?.nodes ?? []) c[n.type] = (c[n.type] ?? 0) + 1;
    return c;
  }, [data]);
  const learned = (data?.edges ?? []).filter((e) => e.kind === "learned_from").length;

  return (
    <>
      <PageHeader
        icon={<IconGraph />}
        title="Task Graph"
        sub="Your whole workspace as a map: projects, tasks, the failures they hit, the files repairs touched, and which fixes were reused."
      />
      {graph.error && <ErrorBox error={graph.error} />}

      <div className="graph-bar">
        <div className="graph-search">
          <span aria-hidden="true">⌕</span>
          <input
            ref={searchBox}
            value={query}
            placeholder="Search tasks, projects, failures, files…  ( / )"
            aria-label="Search the graph"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && matches[0]) flyTo(matches[0].id);
              if (e.key === "Escape") setQuery("");
            }}
          />
          {query && <small className="muted">{matches.length} match{matches.length === 1 ? "" : "es"} · Enter to fly</small>}
        </div>
        <div className="graph-chips" role="group" aria-label="Show node types">
          {TYPES.map((t) => (
            <button key={t.id} type="button" className={`gchip t-${t.id}${types.has(t.id) ? " on" : ""}`} aria-pressed={types.has(t.id)} onClick={() => toggleType(t.id)}>
              <i aria-hidden="true" />
              {t.label}
              <b>{counts[t.id] ?? 0}</b>
            </button>
          ))}
        </div>
        <div className="graph-stats muted small">
          <span><b>{learned}</b> reused fixes</span>
          {data?.truncated && <span title="Only the newest 300 tasks are drawn">newest 300 tasks</span>}
        </div>
      </div>

      <div className="graph-stage">
        <div className="graph-canvas" data-testid="task-graph">
          {data && data.nodes.length === 0 ? (
            <Empty><span className="empty-art" aria-hidden="true">◎</span>Nothing to map yet. Create a task and it will appear here.</Empty>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              minZoom={0.15}
              maxZoom={2.5}
              nodesConnectable={false}
              onNodeClick={(_, n) => pick(n.id)}
              onNodeMouseEnter={(_, n) => setHovered(n.id)}
              onNodeMouseLeave={() => setHovered(null)}
              onPaneClick={() => { setSelected(null); setPath([]); setPathFrom(null); }}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={28} size={1} />
              <MiniMap pannable zoomable className="graph-minimap" nodeClassName={(n) => `mm-${(n.data as OrbData).node.type}`} />
              <Controls showInteractive={false} />
            </ReactFlow>
          )}
          {pathFrom && <div className="graph-hint" role="status">Path mode: click a second node…</div>}
          {graph.loading && !data && <div className="graph-loading" role="status"><span className="orbit"><span /><span /><span /></span>Mapping your workspace…</div>}
        </div>

        <aside className={`inspector${sel ? " open" : ""}`} aria-label="Node details">
          {!sel ? (
            <div className="insp-empty">
              <strong>Explore the map</strong>
              <ul className="muted small">
                <li>Click a node for details and links</li>
                <li>Hover to light up its connections</li>
                <li>Type to search, Enter to fly there</li>
                <li><span className="k-learned-swatch" /> dashed glowing lines = a fix reused from another task</li>
              </ul>
            </div>
          ) : (
            <Inspector
              node={sel}
              neighbours={[...(adj.get(sel.id) ?? [])].map((id) => byId.get(id)).filter((n): n is GraphNode => !!n)}
              onFly={flyTo}
              onPath={() => { setPathFrom(sel.id); setPath([]); }}
              path={path.map((id) => byId.get(id)).filter((n): n is GraphNode => !!n)}
              onClose={() => { setSelected(null); setPath([]); }}
            />
          )}
        </aside>
      </div>
    </>
  );
}

function Inspector({
  node,
  neighbours,
  onFly,
  onPath,
  path,
  onClose,
}: {
  node: GraphNode;
  neighbours: GraphNode[];
  onFly: (id: string) => void;
  onPath: () => void;
  path: GraphNode[];
  onClose: () => void;
}) {
  const taskId = typeof node.meta.task_id === "string" ? node.meta.task_id : null;
  const group = (t: GraphNodeType) => neighbours.filter((n) => n.type === t);
  return (
    <div className="insp">
      <header className="insp-head">
        <span className={`insp-type t-${node.type}`}>{node.type}</span>
        <button type="button" className="link" onClick={onClose} aria-label="Close details">×</button>
      </header>
      <h2 className="insp-title">{node.label}</h2>
      {node.status && <StatusBadge status={node.status} />}
      <dl className="insp-facts">
        {node.type === "task" && (
          <>
            <div><dt>Iterations</dt><dd>{String(node.meta.iterations)} / {String(node.meta.max_iterations)}</dd></div>
            <div><dt>Quality</dt><dd>{node.meta.quality == null ? "—" : Math.round(Number(node.meta.quality))}</dd></div>
            <div><dt>Shares its fixes</dt><dd>{node.meta.learnable ? "yes" : "no"}</dd></div>
          </>
        )}
        {node.type === "project" && (
          <>
            <div><dt>Language</dt><dd>{String(node.meta.language)}</dd></div>
            <div><dt>Tasks</dt><dd>{String(node.meta.tasks)}</dd></div>
          </>
        )}
        {node.type === "failure" && (
          <>
            <div><dt>Repairs</dt><dd>{String(node.meta.count)}</dd></div>
            <div><dt>Resolved</dt><dd>{String(node.meta.resolved)}</dd></div>
          </>
        )}
        {node.type === "file" && <div><dt>Repaired</dt><dd>{String(node.meta.repairs)} times</dd></div>}
      </dl>
      <div className="insp-links">
        {taskId && (
          <>
            <Link className="button primary" to={`/tasks/${taskId}`}>Open live workflow</Link>
            <Link className="button" to={`/tasks/${taskId}/code`}>Code</Link>
            <Link className="button" to={`/tasks/${taskId}/report`}>Report</Link>
          </>
        )}
        {node.type === "failure" && <Link className="button primary" to={`/lessons?class=${encodeURIComponent(node.label)}`}>See the lessons</Link>}
        <button type="button" onClick={onPath}>Find path to…</button>
      </div>
      {path.length > 1 && (
        <section className="insp-path">
          <h3>Path · {path.length - 1} hop{path.length === 2 ? "" : "s"}</h3>
          <ol>{path.map((n) => <li key={n.id}><button type="button" className="link" onClick={() => onFly(n.id)}>{n.label}</button></li>)}</ol>
        </section>
      )}
      {(["project", "task", "failure", "file"] as GraphNodeType[]).map((t) =>
        group(t).length ? (
          <section key={t} className="insp-group">
            <h3>{t === "task" ? "Tasks" : t === "project" ? "Project" : t === "failure" ? "Failures" : "Files"} <span className="muted">{group(t).length}</span></h3>
            <ul>
              {group(t).slice(0, 12).map((n) => (
                <li key={n.id}>
                  <button type="button" className={`insp-item mood-${moodOf(n)}`} onClick={() => onFly(n.id)}>
                    <i aria-hidden="true" />
                    <span>{n.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null,
      )}
    </div>
  );
}
