import { useEffect } from "react";
import { Link } from "react-router";
import { TaskExplorer } from "../components/TaskExplorer";
import { ActivityHeatmap, isRunning, QuickStart, RunningNow, StatusDonut } from "../components/Dashboard";
import { api } from "../api/client";
import { useAuth } from "../auth";
import type { Overview, Task } from "../api/types";
import { IconHome } from "../components/icons";
import { Card, Empty, ErrorBox, Kpi, Loading, PageHeader } from "../components/ui";
import { useAsync } from "../hooks";
import { money, num, pct, seconds } from "../lib/format";

/** Screen 1 — Command Center. KPI definitions: spec §9.1, computed server-side in one place. */
export function CommandCenter() {
  const { can } = useAuth();
  const overview = useAsync(() => api.get<Overview>("/analytics/overview"), []);
  const tasks = useAsync(() => api.get<Task[]>("/tasks", { limit: 50, order: "desc" }), []); // newest first
  const o = overview.data;
  const runningCount = (tasks.data ?? []).filter(isRunning).length;

  // keep the "Running now" panel live: refresh every 4s while anything is running
  const reload = tasks.reload;
  useEffect(() => {
    if (runningCount === 0) return;
    const timer = window.setInterval(() => reload(), 4000);
    return () => window.clearInterval(timer);
  }, [runningCount, reload]);

  return (
    <>
      <PageHeader icon={<IconHome />} title="Command Center" sub="Every loop, every test, every decision — live.">
        {can("developer") && <Link className="button primary" to="/tasks/new">New task</Link>}
      </PageHeader>

      {overview.error && <ErrorBox error={overview.error} />}
      {!o && overview.loading && (
        <div className="kpis" role="status" aria-label="Loading">
          {Array.from({ length: 6 }, (_, i) => <div key={i} className="kpi kpi-skel"><span className="skeleton" /><span className="skeleton big" /></div>)}
        </div>
      )}
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

      <div className={`bento${can("developer") ? "" : " no-qs"}`}>
        <Card title="Running now" actions={runningCount > 0 && <span className="badge live-run">{runningCount} live</span>}>
          <div className="b-run">
            {tasks.data ? <RunningNow tasks={tasks.data} /> : <span className="skeleton" />}
          </div>
        </Card>
        {can("developer") && <div className="b-qs"><QuickStart /></div>}
        <Card title="Status mix">
          <StatusDonut counts={o?.tasks_by_status ?? {}} />
        </Card>
        <Card title="Activity">
          <ActivityHeatmap dates={(tasks.data ?? []).map((t) => t.created_at)} />
        </Card>
        <Link to="/graph" className="graph-tile">
          <span className="gt-sky" aria-hidden="true">
            {Array.from({ length: 14 }, (_, i) => <i key={i} style={{ "--i": i } as React.CSSProperties} />)}
          </span>
          <span className="gt-text">
            <strong>Task Graph</strong>
            <span className="muted small">{(tasks.data ?? []).length} tasks mapped with their failures, files and reused fixes</span>
          </span>
          <span className="gt-go" aria-hidden="true">→</span>
        </Link>
      </div>

      <Card title="Tasks">
        {tasks.error && <ErrorBox error={tasks.error} />}
        {tasks.loading && !tasks.data && <Loading />}
        {tasks.data && tasks.data.length === 0 && <Empty><span className="empty-art" aria-hidden="true">∞</span>No tasks yet. Create one to watch the loop run.</Empty>}
        {tasks.data && tasks.data.length > 0 && (
          <TaskExplorer tasks={tasks.data} canAct={can("developer")} onChanged={tasks.reload} />
        )}
      </Card>
    </>
  );
}
