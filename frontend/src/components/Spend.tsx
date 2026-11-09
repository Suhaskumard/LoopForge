import { useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useAsync } from "../hooks";
import { toast } from "./Toast";
import { Card, Empty, ErrorBox, Loading } from "./ui";

/* ---------- API shapes (GET /orgs/{id}/usage/report, /orgs/{id}/usage) ---------- */

export interface UsageRow {
  key: string;
  label: string;
  tasks: number;
  agent_runs: number;
  tokens: number;
  estimated_cost_usd: number;
  agent_seconds: number;
}
interface UsageReport {
  period: { from: string; to: string };
  group_by: string;
  rows: UsageRow[];
  totals: { tasks: number; agent_runs: number; tokens: number; estimated_cost_usd: number; agent_seconds: number };
}
interface Quota {
  tokens_used: number;
  token_quota_month: number | null;
  tokens_remaining: number | null;
}

/* ---------- pure helpers (unit-tested) ---------- */

const iso = (d: Date) => d.toISOString().slice(0, 10);
const utcDay = (y: number, m: number, d: number) => new Date(Date.UTC(y, m, d));
export const daysInMonth = (d: Date) => utcDay(d.getUTCFullYear(), d.getUTCMonth() + 1, 0).getUTCDate();

/** Every day from `from` to `to` (inclusive, YYYY-MM-DD), zero-filled from the day rows. */
export function fillDays(rows: UsageRow[], from: string, to: string): { day: string; cost: number; tokens: number }[] {
  const byDay = new Map(rows.map((r) => [r.key, r]));
  const out = [];
  for (let d = new Date(`${from}T00:00:00Z`); iso(d) <= to; d = new Date(d.getTime() + 86_400_000)) {
    const r = byDay.get(iso(d));
    out.push({ day: iso(d), cost: r?.estimated_cost_usd ?? 0, tokens: r?.tokens ?? 0 });
  }
  return out;
}

export interface Projection {
  spent: number;
  tokens: number;
  dailyCost: number;
  dailyTokens: number;
  projectedCost: number;
  projectedTokens: number;
  low: number; // band from the quietest / busiest of the last 7 days
  high: number;
  daysLeft: number;
}

/** Month-end projection from this month's daily figures (run-rate × days left). */
export function projectMonth(days: { day: string; cost: number; tokens: number }[], today: Date): Projection {
  const month = iso(today).slice(0, 7);
  const sofar = days.filter((d) => d.day.startsWith(month) && d.day <= iso(today));
  const elapsed = Math.max(1, today.getUTCDate());
  const spent = sofar.reduce((s, d) => s + d.cost, 0);
  const tokens = sofar.reduce((s, d) => s + d.tokens, 0);
  const daysLeft = daysInMonth(today) - today.getUTCDate();
  const dailyCost = spent / elapsed;
  const dailyTokens = tokens / elapsed;
  const recent = sofar.slice(-7).map((d) => d.cost);
  const lo = recent.length ? Math.min(...recent) : 0;
  const hi = recent.length ? Math.max(...recent) : 0;
  return {
    spent,
    tokens,
    dailyCost,
    dailyTokens,
    projectedCost: spent + dailyCost * daysLeft,
    projectedTokens: Math.round(tokens + dailyTokens * daysLeft),
    low: spent + lo * daysLeft,
    high: spent + hi * daysLeft,
    daysLeft,
  };
}

/** The day this month the token quota runs out at the current rate, or null if it will not. */
export function exceedDate(used: number, quota: number | null, dailyTokens: number, today: Date): string | null {
  if (quota === null || dailyTokens <= 0) return null;
  if (used >= quota) return iso(today);
  const day = new Date(today.getTime() + Math.ceil((quota - used) / dailyTokens) * 86_400_000);
  return day.getUTCMonth() === today.getUTCMonth() ? iso(day) : null;
}

/* ---------- component ---------- */

type Range = "month" | "last-month" | "30d";
type Group = "project" | "member" | "agent" | "model";

function rangeOf(r: Range, today: Date): { from: string; to: string } {
  const y = today.getUTCFullYear();
  const m = today.getUTCMonth();
  if (r === "last-month") return { from: iso(utcDay(y, m - 1, 1)), to: iso(utcDay(y, m, 0)) };
  if (r === "30d") return { from: iso(new Date(today.getTime() - 29 * 86_400_000)), to: iso(today) };
  return { from: iso(utcDay(y, m, 1)), to: iso(today) };
}

const usd = (v: number) => (v === 0 ? "$0" : v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);

export function Spend({ orgId }: { orgId: string }) {
  const today = useMemo(() => new Date(), []);
  const [range, setRange] = useState<Range>("month");
  const [group, setGroup] = useState<Group>("project");
  const { from, to } = rangeOf(range, today);
  const base = `/orgs/${orgId}/usage/report`;
  const daily = useAsync(() => api.get<UsageReport>(base, { from, to, group_by: "day" }), [orgId, from, to]);
  const breakdown = useAsync(() => api.get<UsageReport>(base, { from, to, group_by: group }), [orgId, from, to, group]);
  // the projection always looks at the current month, whatever range is on screen
  const thisMonth = rangeOf("month", today);
  const month = useAsync(
    () => api.get<UsageReport>(base, { from: thisMonth.from, to: thisMonth.to, group_by: "day" }),
    [orgId, thisMonth.from],
  );
  const quota = useAsync(() => api.get<Quota>(`/orgs/${orgId}/usage`), [orgId]);

  const days = useMemo(() => (daily.data ? fillDays(daily.data.rows, from, to) : []), [daily.data, from, to]);
  const proj = useMemo(
    () => (month.data ? projectMonth(fillDays(month.data.rows, thisMonth.from, thisMonth.to), today) : null),
    [month.data, thisMonth.from, thisMonth.to, today],
  );
  const q = quota.data;
  const runsOut = proj && q ? exceedDate(q.tokens_used, q.token_quota_month, proj.dailyTokens, today) : null;
  const quotaPct = q && q.token_quota_month ? Math.min(100, (q.tokens_used / q.token_quota_month) * 100) : null;
  const rows = [...(breakdown.data?.rows ?? [])].sort((a, b) => b.estimated_cost_usd - a.estimated_cost_usd || b.tokens - a.tokens);
  const totalCost = breakdown.data?.totals.estimated_cost_usd ?? 0;

  const exportCsv = async () => {
    try {
      const blob = await api.blob(`${base}.csv?from=${from}&to=${to}&group_by=${group}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `usage-${from}-${to}-${group}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Export failed", "bad");
    }
  };

  return (
    <div className="spend">
      <div className="spend-hero">
        <div className="sh-main">
          <span className="pv-kicker">This month · estimated</span>
          <strong className="sh-big" data-testid="spend-mtd">{proj ? usd(proj.spent) : "—"}</strong>
          <span className="muted small">{proj ? `${proj.tokens.toLocaleString()} tokens so far · ${usd(proj.dailyCost)}/day` : " "}</span>
        </div>
        <div className="sh-proj">
          <span className="pv-kicker">Projected month end</span>
          <strong data-testid="spend-projection">{proj ? usd(proj.projectedCost) : "—"}</strong>
          {proj && proj.daysLeft > 0 && <span className="muted small">likely {usd(proj.low)} – {usd(proj.high)}</span>}
        </div>
        <div className="sh-quota">
          <span className="pv-kicker">Token quota</span>
          {quotaPct === null ? (
            <strong>No monthly cap</strong>
          ) : (
            <>
              <span className="quota-bar" aria-hidden="true"><i className={quotaPct > 90 ? "hot" : ""} style={{ width: `${quotaPct}%` }} /></span>
              <span className="small">{q!.tokens_used.toLocaleString()} / {q!.token_quota_month!.toLocaleString()}</span>
            </>
          )}
          {runsOut && <span className="sh-warn small" role="status">At this rate the quota runs out on {runsOut}.</span>}
        </div>
      </div>

      <div className="row spend-controls">
        <div className="seg" role="group" aria-label="Period">
          {([["month", "This month"], ["last-month", "Last month"], ["30d", "Last 30 days"]] as [Range, string][]).map(([id, label]) => (
            <button key={id} type="button" className={range === id ? "on" : ""} aria-pressed={range === id} onClick={() => setRange(id)}>{label}</button>
          ))}
        </div>
        <button type="button" onClick={() => void exportCsv()}>Export CSV</button>
        <span className="muted small">Costs are estimates from token counts and your price map, not billing data.</span>
      </div>

      <Card title="Daily spend">
        {daily.error && <ErrorBox error={daily.error} />}
        {!daily.data && daily.loading && <Loading what="Loading usage" />}
        {daily.data && (days.every((d) => d.cost === 0 && d.tokens === 0) ? (
          <Empty>No agent activity in this period yet.</Empty>
        ) : (
          <div className="chart spend-chart">
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={days} margin={{ left: 4, right: 12, top: 8 }}>
                <defs>
                  <linearGradient id="spend-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor="#8b7bff" stopOpacity={0.55} />
                    <stop offset="1" stopColor="#38d5f5" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tickFormatter={(d: string) => d.slice(5)} minTickGap={18} />
                <YAxis tickFormatter={(v: number) => usd(v)} width={64} />
                <Tooltip formatter={(v: number) => usd(v)} labelFormatter={(d: string) => d} />
                {proj && range === "month" && <ReferenceLine y={proj.dailyCost} stroke="#38d5f5" strokeDasharray="6 4" label={{ value: "avg/day", fill: "#38d5f5", fontSize: 11, position: "insideTopRight" }} />}
                <Area type="monotone" dataKey="cost" name="Est. cost" stroke="#8b7bff" strokeWidth={2.5} fill="url(#spend-fill)" animationDuration={1000} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ))}
      </Card>

      <Card
        title="Where it goes"
        actions={
          <div className="seg" role="group" aria-label="Break down by">
            {(["project", "member", "agent", "model"] as Group[]).map((g) => (
              <button key={g} type="button" className={group === g ? "on" : ""} aria-pressed={group === g} onClick={() => setGroup(g)}>{g}</button>
            ))}
          </div>
        }
      >
        {breakdown.error && <ErrorBox error={breakdown.error} />}
        {breakdown.data && rows.length === 0 && <Empty>Nothing to break down yet.</Empty>}
        <ul className="spend-rows">
          {rows.map((r) => {
            const share = totalCost > 0 ? r.estimated_cost_usd / totalCost : 0;
            return (
              <li key={r.key}>
                <span className="sr-label">{r.label || r.key}</span>
                <span className="sr-bar" aria-hidden="true"><i style={{ width: `${Math.max(2, share * 100)}%` }} /></span>
                <span className="sr-cost">{usd(r.estimated_cost_usd)}</span>
                <span className="sr-meta muted small">{Math.round(share * 100)}% · {r.tokens.toLocaleString()} tok · {r.tasks} task{r.tasks === 1 ? "" : "s"}</span>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}
