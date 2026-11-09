import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { RepairRecord } from "../api/types";
import { IconBulb } from "../components/icons";
import { Card, Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { useAsync } from "../hooks";

export interface LessonClass {
  name: string;
  total: number;
  resolved: number;
  avgTokens: number;
  tasks: number;
  reusable: number; // resolved fixes from tasks that share what they learn
  last: string;
}

/** Group repair records into failure classes, busiest first. */
export function summarize(rows: RepairRecord[]): LessonClass[] {
  const by = new Map<string, RepairRecord[]>();
  for (const r of rows) by.set(r.failure_class, [...(by.get(r.failure_class) ?? []), r]);
  return [...by.entries()]
    .map(([name, rs]) => ({
      name,
      total: rs.length,
      resolved: rs.filter((r) => r.outcome === "resolved").length,
      avgTokens: Math.round(rs.reduce((n, r) => n + r.tokens_used, 0) / rs.length),
      tasks: new Set(rs.map((r) => r.task_id)).size,
      reusable: rs.filter((r) => r.outcome === "resolved" && r.learnable).length,
      last: rs.map((r) => r.created_at).sort().at(-1) ?? "",
    }))
    .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
}

/** Repair Memory: what the Repair agent has tried and learned in this organization. */
export function Lessons() {
  const repairs = useAsync(() => api.get<RepairRecord[]>("/repairs", { limit: 500 }), []);
  const [params, setParams] = useSearchParams();
  const active = params.get("class");
  const rows = useMemo(() => repairs.data ?? [], [repairs.data]);
  const classes = useMemo(() => summarize(rows), [rows]);
  const detail = active ? rows.filter((r) => r.failure_class === active) : [];
  const resolvedAll = rows.filter((r) => r.outcome === "resolved").length;

  return (
    <>
      <PageHeader
        icon={<IconBulb />}
        title="Lessons"
        sub="Repair memory: every failure the loop hit, what it tried, and which fixes it can reuse on future tasks."
      />
      {repairs.error && <ErrorBox error={repairs.error} />}
      {repairs.loading && !repairs.data && <Loading what="Reading repair memory" />}
      {repairs.data && rows.length === 0 && (
        <Empty><span className="empty-art" aria-hidden="true">✦</span>No repairs yet. When a test fails and the Repair agent fixes it, the lesson shows up here.</Empty>
      )}

      {rows.length > 0 && (
        <div className="lesson-summary">
          <div><b>{rows.length}</b><span>repairs</span></div>
          <div><b>{classes.length}</b><span>failure classes</span></div>
          <div><b>{Math.round((resolvedAll / rows.length) * 100)}%</b><span>resolved</span></div>
          <div><b>{rows.filter((r) => r.outcome === "resolved" && r.learnable).length}</b><span>reusable fixes</span></div>
        </div>
      )}

      <div className="lesson-grid">
        {classes.map((c, i) => {
          const rate = c.total ? c.resolved / c.total : 0;
          return (
            <button
              key={c.name}
              type="button"
              className={`lesson-card${active === c.name ? " on" : ""}`}
              style={{ animationDelay: `${Math.min(i, 10) * 0.04}s` }}
              aria-pressed={active === c.name}
              onClick={() => setParams(active === c.name ? {} : { class: c.name })}
            >
              <span className="lc-ring" aria-hidden="true" style={{ "--p": `${rate * 100}` } as React.CSSProperties}>
                <span>{Math.round(rate * 100)}%</span>
              </span>
              <span className="lc-body">
                <strong>{c.name}</strong>
                <span className="muted small">{c.total} repair{c.total === 1 ? "" : "s"} · {c.tasks} task{c.tasks === 1 ? "" : "s"} · ~{c.avgTokens.toLocaleString()} tok</span>
                <span className="lc-tags">
                  {c.reusable > 0 && <span className="badge ok">{c.reusable} reusable</span>}
                  {c.total - c.resolved > 0 && <span className="badge bad">{c.total - c.resolved} unresolved</span>}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {active && (
        <Card
          title={`${active} · what the loop tried`}
          actions={<Link className="button" to={`/graph?q=${encodeURIComponent(active)}`}>Show in graph</Link>}
        >
          {detail.length === 0 ? (
            <Empty>No repairs in this class.</Empty>
          ) : (
            <ol className="lesson-list">
              {detail.map((r) => (
                <li key={r.id} className={`lesson ${r.outcome === "resolved" ? "ok" : "bad"}`}>
                  <div className="lesson-top">
                    <span className={`badge ${r.outcome === "resolved" ? "ok" : "bad"}`}>{r.outcome || "unknown"}</span>
                    {r.learnable && r.outcome === "resolved" && <span className="badge">reusable</span>}
                    <Link to={`/tasks/${r.task_id}`} className="lesson-task">{r.task_requirement}</Link>
                    <time className="muted small">{new Date(r.created_at + (r.created_at.endsWith("Z") ? "" : "Z")).toLocaleString()}</time>
                  </div>
                  <div className="lesson-flow">
                    <div><span className="lf-k">Cause</span><p>{r.root_cause || "—"}</p></div>
                    <span className="lf-arrow" aria-hidden="true">→</span>
                    <div><span className="lf-k">Fix</span><p>{r.proposed_fix || "—"}</p></div>
                  </div>
                  {r.files_modified.length > 0 && (
                    <div className="lesson-files">{r.files_modified.map((f) => <code key={f}>{f}</code>)}</div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}
    </>
  );
}
