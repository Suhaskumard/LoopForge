import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { AgentStat, Overview, TaskAnalytics } from "../api/types";
import { Card, Empty, ErrorBox, Kpi, Loading } from "../components/ui";
import { useAsync } from "../hooks";
import { money, num, pct } from "../lib/format";

const COLORS = { ok: "#2f9e6b", bad: "#d9534f", blue: "#4c7be8", amber: "#d89b2b" };

/** Screen 6 — Loop Analytics (+ Addendum 22.11 engineering-intelligence views). */
export function Analytics() {
  const overview = useAsync(() => api.get<Overview>("/analytics/overview"), []);
  const agents = useAsync(() => api.get<AgentStat[]>("/analytics/agents"), []);
  const recent = overview.data?.recent_tasks ?? [];
  const perTask = useAsync(
    () => Promise.all(recent.map((t) => api.get<TaskAnalytics>(`/analytics/tasks/${t.id}`))),
    [recent.map((t) => t.id).join(",")],
  );
  const [pick, setPick] = useState<string>();
  const o = overview.data;

  const selected = perTask.data?.find((t) => t.task_id === pick) ?? perTask.data?.[0];
  const quality = (selected?.iterations ?? []).map((i) => ({
    iteration: `v${i.number}`,
    quality: i.quality_score === null ? null : Math.round(i.quality_score * 100),
    passed: i.tests_passed,
    failed: i.tests_failed,
  }));
  const perTaskRows = useMemo(
    () =>
      (perTask.data ?? []).map((t, i) => ({
        task: `#${i + 1}`,
        iterations: t.iterations.length,
        cost: Number(t.estimated_cost.toFixed(5)),
      })),
    [perTask.data],
  );
  const failureRows = Object.entries(o?.failure_distribution ?? {}).map(([category, count]) => ({ category, count }));
  const outcomeRows = Object.entries(o?.repair_outcomes ?? {}).map(([category, v]) => ({
    category,
    resolved: v["resolved"] ?? 0,
    unresolved: (v["unresolved"] ?? 0) + (v["pending"] ?? 0),
  }));
  const agentRows = (agents.data ?? []).map((a) => ({ agent: a.agent, success: a.success_rate ?? 0, runs: a.runs }));

  return (
    <>
      <header className="page-head"><h1>Loop Analytics</h1></header>
      {overview.error && <ErrorBox error={overview.error} />}
      {!o && overview.loading && <Loading />}
      {o && (
        <div className="kpis">
          <Kpi label="Iteration efficiency" value={num(o.iteration_efficiency, 3)} hint="successful tasks ÷ iterations" />
          <Kpi label="Total tokens" value={o.total_tokens.toLocaleString()} />
          <Kpi label="Estimated spend" value={money(o.total_cost)} hint="estimate: tokens × configured rate" />
          <Kpi label="Test pass rate" value={pct(o.test_pass_rate)} />
        </div>
      )}

      <div className="grid2">
        <Card
          title="Quality improvement per iteration"
          actions={perTask.data && perTask.data.length > 0 && (
            <select value={selected?.task_id} onChange={(e) => setPick(e.target.value)} aria-label="Task">
              {perTask.data.map((t, i) => <option key={t.task_id} value={t.task_id}>Task #{i + 1} ({t.status})</option>)}
            </select>
          )}
        >
          {quality.length === 0 ? <Empty>No iterations yet.</Empty> : (
            <div className="chart"><ResponsiveContainer width="100%" height={240}>
              <LineChart data={quality}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="iteration" /><YAxis domain={[0, 100]} /><Tooltip /><Legend />
                <Line type="monotone" dataKey="quality" name="Quality (0–100)" stroke={COLORS.blue} connectNulls />
                <Line type="monotone" dataKey="passed" name="Tests passed" stroke={COLORS.ok} />
                <Line type="monotone" dataKey="failed" name="Tests failed" stroke={COLORS.bad} />
              </LineChart>
            </ResponsiveContainer></div>
          )}
        </Card>

        <Card title="Iterations and cost per task">
          {perTaskRows.length === 0 ? <Empty>No tasks yet.</Empty> : (
            <div className="chart"><ResponsiveContainer width="100%" height={240}>
              <BarChart data={perTaskRows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="task" /><YAxis yAxisId="l" allowDecimals={false} /><YAxis yAxisId="r" orientation="right" />
                <Tooltip /><Legend />
                <Bar yAxisId="l" dataKey="iterations" name="Iterations" fill={COLORS.blue} />
                <Bar yAxisId="r" dataKey="cost" name="Est. cost ($)" fill={COLORS.amber} />
              </BarChart>
            </ResponsiveContainer></div>
          )}
        </Card>

        <Card title="Failure distribution">
          {failureRows.length === 0 ? <Empty>No failures recorded — nothing needed repair.</Empty> : (
            <div className="chart"><ResponsiveContainer width="100%" height={240}>
              <BarChart data={failureRows} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} /><YAxis type="category" dataKey="category" width={130} />
                <Tooltip /><Bar dataKey="count" name="Failures" fill={COLORS.bad} />
              </BarChart>
            </ResponsiveContainer></div>
          )}
        </Card>

        <Card title="Agent performance">
          {agents.error && <ErrorBox error={agents.error} />}
          {agentRows.every((a) => a.runs === 0) ? <Empty>No agent runs yet.</Empty> : (
            <div className="chart"><ResponsiveContainer width="100%" height={240}>
              <BarChart data={agentRows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="agent" /><YAxis domain={[0, 100]} /><Tooltip />
                <Bar dataKey="success" name="Success rate (%)" fill={COLORS.ok} />
              </BarChart>
            </ResponsiveContainer></div>
          )}
          {agents.data && (
            <table className="table" data-testid="agent-table">
              <thead><tr><th>Agent</th><th>Runs</th><th>Success</th><th>Avg time</th><th>Tokens</th></tr></thead>
              <tbody>
                {agents.data.map((a) => (
                  <tr key={a.agent}>
                    <td>{a.agent}</td><td>{a.runs}</td><td>{pct(a.success_rate, 0)}</td>
                    <td>{a.average_duration_seconds === null ? "—" : `${a.average_duration_seconds.toFixed(2)} s`}</td>
                    <td>{a.tokens.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title="Repair intelligence (by failure category)">
        {outcomeRows.length === 0 ? <Empty>No repairs yet.</Empty> : (
          <div className="chart"><ResponsiveContainer width="100%" height={220}>
            <BarChart data={outcomeRows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="category" /><YAxis allowDecimals={false} /><Tooltip /><Legend />
              <Bar dataKey="resolved" name="Resolved" stackId="a" fill={COLORS.ok} />
              <Bar dataKey="unresolved" name="Unresolved" stackId="a" fill={COLORS.bad} />
            </BarChart>
          </ResponsiveContainer></div>
        )}
      </Card>
    </>
  );
}
