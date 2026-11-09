import { useState } from "react";
import { api } from "../api/client";
import type { TaskPlan } from "../api/types";
import { useAsync } from "../hooks";

/** The Planner's validated plan: requirements, the files it intends to write, and dependencies. */
export function PlanPanel({ taskId, signal }: { taskId: string; signal: number }) {
  const plan = useAsync(
    () => api.get<TaskPlan>(`/tasks/${taskId}/plan`).catch(() => null), // 404 = no plan yet
    [taskId, signal > 0],
  );
  const [open, setOpen] = useState(true);
  const p = plan.data?.plan;
  if (!p) return null;
  const reqs = p.requirements ?? [];
  const files = p.files ?? [];
  return (
    <section className={`plan-panel${open ? " open" : ""}`} aria-label="Plan">
      <button type="button" className="plan-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="plan-icon" aria-hidden="true">✦</span>
        <span className="plan-title">
          <strong>The plan</strong>
          <span className="muted small">
            {p.project_name ?? "project"} · {p.framework ?? ""} · {reqs.length} requirements · {files.length} files
            {plan.data?.iteration ? ` · from iteration ${plan.data.iteration}` : ""}
          </span>
        </span>
        <span className="plan-chev" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="plan-body">
          <div className="plan-col">
            <h3>Requirements</h3>
            <ul className="plan-reqs">
              {reqs.map((r) => (
                <li key={r.req_id}>
                  <code>{r.req_id}</code>
                  <span>{r.description}</span>
                  {r.priority && <span className={`badge ${r.priority === "high" ? "warn" : "muted"}`}>{r.priority}</span>}
                </li>
              ))}
            </ul>
          </div>
          <div className="plan-col">
            <h3>Files</h3>
            <ul className="plan-files">
              {files.map((f) => (
                <li key={f.path}>
                  <code>{f.path}</code>
                  <span className="muted small">{f.purpose}</span>
                  {f.implements && f.implements.length > 0 && <span className="plan-impl">{f.implements.join(" · ")}</span>}
                </li>
              ))}
            </ul>
            {(p.dependencies ?? []).length > 0 && (
              <>
                <h3>Dependencies</h3>
                <div className="plan-deps">{p.dependencies!.map((d) => <code key={d}>{d}</code>)}</div>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
