import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { Task } from "../api/types";
import { isTerminal } from "../api/types";
import { toast } from "./Toast";
import { StatusBadge } from "./ui";

export type Sort = "newest" | "oldest" | "iterations";
type Bulk = "cancel" | "retry" | "rerun";

const GROUPS: { id: string; label: string; match: (t: Task) => boolean }[] = [
  { id: "running", label: "Running", match: (t) => !isTerminal(t.status) && t.status !== "PENDING" },
  { id: "COMPLETED", label: "Accepted", match: (t) => t.status === "COMPLETED" },
  { id: "needs", label: "Needs attention", match: (t) => t.status === "FAILED" || t.status === "ESCALATED" },
  { id: "PENDING", label: "Pending", match: (t) => t.status === "PENDING" },
  { id: "CANCELLED", label: "Cancelled", match: (t) => t.status === "CANCELLED" },
];

/** Filter + sort, pure so it can be unit-tested. */
export function explore(tasks: Task[], q: string, group: string, sort: Sort): Task[] {
  const needle = q.trim().toLowerCase();
  const g = GROUPS.find((x) => x.id === group);
  const out = tasks.filter((t) => (!g || g.match(t)) && (!needle || t.requirement.toLowerCase().includes(needle)));
  const time = (t: Task) => Date.parse(t.created_at);
  return out.sort((a, b) =>
    sort === "oldest" ? time(a) - time(b) : sort === "iterations" ? b.current_iteration - a.current_iteration || time(b) - time(a) : time(b) - time(a),
  );
}

/** Which bulk actions apply to a task. */
export function actionsFor(t: Task): Bulk[] {
  if (t.status === "COMPLETED") return ["rerun"];
  if (t.status === "FAILED" || t.status === "ESCALATED") return ["retry"];
  if (!isTerminal(t.status) && t.status !== "PENDING") return ["cancel"];
  return [];
}

const LABEL: Record<Bulk, string> = { cancel: "Cancel", retry: "Retry", rerun: "Re-run" };

export function TaskExplorer({ tasks, canAct, onChanged }: { tasks: Task[]; canAct: boolean; onChanged: () => void }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const group = params.get("status") ?? "";
  const sort = (params.get("sort") as Sort) || "newest";
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  const rows = useMemo(() => explore(tasks, q, group, sort), [tasks, q, group, sort]);
  const counts = useMemo(() => Object.fromEntries(GROUPS.map((g) => [g.id, tasks.filter(g.match).length])), [tasks]);
  const picked = rows.filter((t) => selected.has(t.id));
  const possible = (["cancel", "retry", "rerun"] as Bulk[]).filter((a) => picked.some((t) => actionsFor(t).includes(a)));
  const toggle = (id: string) =>
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allShown = rows.length > 0 && rows.every((t) => selected.has(t.id));

  const run = async (action: Bulk) => {
    const targets = picked.filter((t) => actionsFor(t).includes(action));
    setBusy(true);
    const failed: string[] = [];
    for (const t of targets) {
      try {
        if (action === "cancel") await api.post(`/tasks/${t.id}/cancel`);
        if (action === "retry") {
          await api.post(`/tasks/${t.id}/retry`);
          await api.post(`/tasks/${t.id}/start`);
        }
        if (action === "rerun") await api.post(`/tasks/${t.id}/rerun`);
      } catch (e) {
        failed.push(`${t.requirement.slice(0, 40)}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }
    setBusy(false);
    setSelected(new Set());
    const ok = targets.length - failed.length;
    if (ok) toast(`${LABEL[action]}: ${ok} task${ok === 1 ? "" : "s"}`, "ok");
    for (const f of failed.slice(0, 3)) toast(f, "bad");
    onChanged();
  };

  return (
    <>
      <div className="explorer-bar">
        <input
          className="explorer-search"
          value={q}
          placeholder="Search requirements…"
          aria-label="Search tasks"
          onChange={(e) => set("q", e.target.value)}
        />
        <div className="graph-chips" role="group" aria-label="Filter by status">
          <button type="button" className={`gchip${group === "" ? " on" : ""}`} aria-pressed={group === ""} onClick={() => set("status", "")}>
            All <b>{tasks.length}</b>
          </button>
          {GROUPS.map((g) => (
            <button key={g.id} type="button" className={`gchip st-${g.id}${group === g.id ? " on" : ""}`} aria-pressed={group === g.id} onClick={() => set("status", group === g.id ? "" : g.id)}>
              <i aria-hidden="true" />
              {g.label} <b>{counts[g.id]}</b>
            </button>
          ))}
        </div>
        <label className="explorer-sort">
          Sort
          <select value={sort} onChange={(e) => set("sort", e.target.value === "newest" ? "" : e.target.value)}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="iterations">Most iterations</option>
          </select>
        </label>
      </div>

      {canAct && picked.length > 0 && (
        <div className="bulk-bar" role="region" aria-label="Bulk actions">
          <b>{picked.length} selected</b>
          {possible.length === 0 && <span className="muted small">No action applies to these tasks.</span>}
          {possible.map((a) => (
            <button key={a} type="button" className={a === "cancel" ? "danger" : "primary"} disabled={busy} onClick={() => void run(a)}>
              {LABEL[a]} ({picked.filter((t) => actionsFor(t).includes(a)).length})
            </button>
          ))}
          <button type="button" className="link" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      {rows.length === 0 ? (
        <p className="muted explorer-none">No tasks match.</p>
      ) : (
        <table className="table" data-testid="task-table">
          <thead>
            <tr>
              {canAct && (
                <th className="sel-col">
                  <input
                    type="checkbox"
                    aria-label="Select all shown tasks"
                    checked={allShown}
                    onChange={() => setSelected(allShown ? new Set() : new Set(rows.map((t) => t.id)))}
                  />
                </th>
              )}
              <th>Requirement</th><th>Status</th><th>Iteration</th><th>Created</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} className={selected.has(t.id) ? "picked" : ""}>
                {canAct && (
                  <td className="sel-col">
                    <input type="checkbox" aria-label={`Select ${t.requirement.slice(0, 60)}`} checked={selected.has(t.id)} onChange={() => toggle(t.id)} />
                  </td>
                )}
                <td>
                  <Link to={`/tasks/${t.id}`}>{t.requirement.slice(0, 90)}</Link>
                  {t.source_type === "task" && <span className="tag-chain" title="Continues another task">⛓</span>}
                  {t.experiment && <span className="tag-ab" title="A/B variant">A/B</span>}
                  {t.rerun_of && !t.experiment && <span className="tag-rerun" title="Regression re-run">↻</span>}
                </td>
                <td><StatusBadge status={t.status} /></td>
                <td>
                  {t.current_iteration} / {t.max_iterations}
                  <span className="meter" aria-hidden="true">
                    <i style={{ width: `${Math.min(100, (t.current_iteration / Math.max(1, t.max_iterations)) * 100)}%` }} />
                  </span>
                </td>
                <td className="muted">{new Date(t.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
