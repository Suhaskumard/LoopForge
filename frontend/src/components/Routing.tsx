import { useState } from "react";
import { api } from "../api/client";
import type { ModelStat, Routing as RoutingT } from "../api/types";
import { useAsync } from "../hooks";
import { toast } from "./Toast";
import { Card, ErrorBox, Loading } from "./ui";

const AGENTS = ["Planner", "Builder", "Repair", "Reviewer", "Documentation", "Explainer"] as const;
const usd = (v: number) => (v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(3)}`);

/** Cost (x) vs acceptance (y) for one agent's models, as a tiny SVG scatter. */
export function Scatter({ points, pick }: { points: ModelStat[]; pick: string | null }) {
  const W = 220;
  const H = 120;
  const pad = 18;
  const maxCost = Math.max(...points.map((p) => p.cost_per_run), 1e-9);
  const x = (c: number) => pad + (c / maxCost) * (W - pad * 2);
  const y = (r: number) => H - pad - r * (H - pad * 2);
  return (
    <svg className="rt-scatter" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${points.length} models by cost and acceptance`}>
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} className="rt-axis" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} className="rt-axis" />
      <text x={W - pad} y={H - 4} textAnchor="end" className="rt-label">cost →</text>
      <text x={4} y={pad - 6} className="rt-label">accepted ↑</text>
      {points.map((p) => (
        <g key={p.model} className={p.model === pick ? "rt-pick" : ""}>
          <circle cx={x(p.cost_per_run)} cy={y(p.accept_rate ?? 0)} r={p.model === pick ? 6 : 4.5} />
          <title>{`${p.model}: ${Math.round((p.accept_rate ?? 0) * 100)}% accepted, ${usd(p.cost_per_run)}/run, ${p.tasks} tasks`}</title>
        </g>
      ))}
    </svg>
  );
}

/** Admin → Models: organization-wide model per agent, learned from this org's own runs. */
export function RoutingPanel({ orgId, canEdit }: { orgId: string; canEdit: boolean }) {
  const data = useAsync(() => api.get<RoutingT>(`/orgs/${orgId}/routing`), [orgId]);
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const current = draft ?? data.data?.routing ?? {};
  const save = async (routing: Record<string, string>, ok: string) => {
    setBusy(true);
    try {
      await api.put(`/orgs/${orgId}/routing`, { routing });
      toast(ok, "ok");
      setDraft(null);
      data.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "bad");
    } finally {
      setBusy(false);
    }
  };
  if (data.error) return <ErrorBox error={data.error} />;
  if (!data.data) return <Loading what="Reading model performance" />;
  const d = data.data;
  const noEvidence = d.stats.length === 0;
  return (
    <div className="routing">
      <p className="muted rt-intro">
        Which model each agent uses for <b>every task in this organization</b>. Recommendations come from your own runs in the last {d.window_days} days:
        the cheapest model whose tasks are accepted within 10 points of the best one. A task&apos;s own A/B setting still wins.
      </p>
      {noEvidence && (
        <p className="sh-warn small">No runs with a recorded model yet. With the local demo model nothing is recorded, so recommendations appear once a real provider has run some tasks.</p>
      )}
      <div className="rt-grid">
        {AGENTS.map((agent) => {
          const rec = d.recommendations.find((r) => r.agent === agent);
          const pts = d.stats.filter((s) => s.agent === agent && s.accept_rate !== null);
          const value = current[agent] ?? "";
          return (
            <section key={agent} className="rt-card">
              <header>
                <strong>{agent}</strong>
                <span className="muted small">{value || "server default"}</span>
              </header>
              {pts.length > 0 ? <Scatter points={pts} pick={rec?.model ?? null} /> : <div className="rt-empty muted small">No evidence yet</div>}
              <p className="small rt-reason">{rec?.model ? <><b>Recommended: {rec.model}</b> — {rec.reason}</> : rec?.reason}</p>
              {canEdit && (
                <div className="rt-edit">
                  <label>
                    Model for {agent}
                    <input
                      value={value}
                      placeholder="server default"
                      pattern="[A-Za-z0-9._:/\-]{1,80}"
                      onChange={(e) => setDraft({ ...current, [agent]: e.target.value })}
                    />
                  </label>
                  {rec?.model && rec.model !== value && (
                    <button type="button" className="primary" disabled={busy} onClick={() => void save({ ...current, [agent]: rec.model! }, `${agent} now uses ${rec.model}`)}>
                      Apply recommendation
                    </button>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
      {canEdit && draft && (
        <div className="row rt-save">
          <button type="button" className="primary" disabled={busy} onClick={() => void save(draft, "Model routing saved")}>Save changes</button>
          <button type="button" onClick={() => setDraft(null)}>Discard</button>
        </div>
      )}
      {d.stats.length > 0 && (
        <Card title="The evidence">
          <table className="table">
            <thead><tr><th>Agent</th><th>Model</th><th>Tasks</th><th>Accepted</th><th>Tokens/run</th><th>Cost/run</th></tr></thead>
            <tbody>
              {d.stats.map((s) => (
                <tr key={`${s.agent}:${s.model}`}>
                  <td>{s.agent}</td>
                  <td><code>{s.model}</code></td>
                  <td>{s.tasks}</td>
                  <td>{s.accept_rate === null ? "—" : `${Math.round(s.accept_rate * 100)}%`}</td>
                  <td>{Math.round(s.tokens_per_run).toLocaleString()}</td>
                  <td>{usd(s.cost_per_run)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
