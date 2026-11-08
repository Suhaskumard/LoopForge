import { Link } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../auth";
import type { Overview, Task } from "../api/types";
import { Card, Empty, ErrorBox, Kpi, Loading, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";
import { money, num, pct, seconds } from "../lib/format";

/** Screen 1 — Command Center. KPI definitions: spec §9.1, computed server-side in one place. */
export function CommandCenter() {
  const { can } = useAuth();
  const overview = useAsync(() => api.get<Overview>("/analytics/overview"), []);
  const tasks = useAsync(() => api.get<Task[]>("/tasks", { limit: 50 }), []);
  const o = overview.data;

  return (
    <>
      <header className="page-head">
        <h1>Command Center</h1>
        {can("developer") && <Link className="button primary" to="/tasks/new">New task</Link>}
      </header>

      {overview.error && <ErrorBox error={overview.error} />}
      {!o && overview.loading && <Loading />}
      {o && (
        <div className="kpis">
          <Kpi label="Task success rate" value={pct(o.task_success_rate)} hint={`${o.completed} of ${o.eligible_finished} finished`} />
          <Kpi label="Average iterations" value={num(o.average_iterations)} hint="per completed task" />
          <Kpi label="Test pass rate" value={pct(o.test_pass_rate)} hint={`${o.tests_passed} of ${o.tests_executed} tests`} />
          <Kpi label="Average quality" value={num(o.average_quality_score)} hint="accepted tasks, 0–100" />
          <Kpi label="Average execution time" value={seconds(o.average_execution_seconds)} hint="completed tasks" />
          <Kpi label="Average cost" value={money(o.average_cost)} hint={o.cost_is_estimate ? "estimate: tokens × rate" : ""} />
        </div>
      )}

      <Card title="Tasks">
        {tasks.error && <ErrorBox error={tasks.error} />}
        {tasks.loading && !tasks.data && <Loading />}
        {tasks.data && tasks.data.length === 0 && <Empty>No tasks yet. Create one to watch the loop run.</Empty>}
        {tasks.data && tasks.data.length > 0 && (
          <table className="table" data-testid="task-table">
            <thead>
              <tr><th>Requirement</th><th>Status</th><th>Iteration</th><th>Created</th></tr>
            </thead>
            <tbody>
              {tasks.data.map((t) => (
                <tr key={t.id}>
                  <td><Link to={`/tasks/${t.id}`}>{t.requirement.slice(0, 90)}</Link></td>
                  <td><StatusBadge status={t.status} /></td>
                  <td>{t.current_iteration} / {t.max_iterations}</td>
                  <td className="muted">{new Date(t.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
