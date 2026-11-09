import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api/client";
import type { Experiment, Forecast, Task, Variant, WatchStatus } from "../api/types";
import { useAsync } from "../hooks";
import { toast } from "./Toast";
import { Card, StatusBadge } from "./ui";

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");
const money = (v: number) => (v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);
const dur = (s: number) => (s < 90 ? `${Math.round(s)}s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);

/* ---------- 1. forecast ---------- */

export interface BudgetRisk {
  tokens: boolean;
  cost: boolean;
}

/** A budget below what half of similar tasks needed will probably escalate on budget. */
export function budgetRisk(f: Forecast | null | undefined, tokenBudget: number | null, maxCost: number | null): BudgetRisk {
  return {
    tokens: !!f?.tokens && tokenBudget !== null && tokenBudget < f.tokens.p50,
    cost: !!f?.cost && maxCost !== null && maxCost < f.cost.p50,
  };
}

export function ForecastBlock({
  language,
  words,
  tokenBudget,
  maxCost,
}: {
  language: string;
  words: number;
  tokenBudget: number | null;
  maxCost: number | null;
}) {
  const bucket = Math.max(1, Math.round(words / 5) * 5); // refetch per ~5 words, not per keystroke
  const [f, setF] = useState<Forecast | null>(null);
  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => {
      api
        .get<Forecast>("/forecast", { language: language === "javascript" ? "javascript" : language, words: bucket })
        .then((r) => alive && r && typeof r.basis === "number" && setF(r))
        .catch(() => undefined);
    }, 350);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [language, bucket]);
  if (!f || f.basis === 0) return null;
  const risk = budgetRisk(f, tokenBudget, maxCost);
  const scope = f.scope === "similar" ? "similar tasks" : f.scope === "language" ? `${language} tasks` : "your tasks";
  return (
    <div className="forecast" aria-label="Forecast" data-testid="forecast">
      <div className="fc-head">
        <span className="pv-kicker">Forecast</span>
        <span className="muted small">from {f.basis} finished {scope}</span>
      </div>
      <div className="fc-grid">
        {f.cost && (
          <div className={risk.cost ? "risk" : ""}>
            <span>Cost</span>
            <b>{money(f.cost.p50)}</b>
            <small>up to {money(f.cost.p90)}</small>
          </div>
        )}
        {f.tokens && (
          <div className={risk.tokens ? "risk" : ""}>
            <span>Tokens</span>
            <b>{Math.round(f.tokens.p50).toLocaleString()}</b>
            <small>up to {Math.round(f.tokens.p90).toLocaleString()}</small>
          </div>
        )}
        {f.iterations && (
          <div>
            <span>Rounds</span>
            <b>{f.iterations.p50}</b>
            <small>up to {f.iterations.p90}</small>
          </div>
        )}
        {f.seconds && (
          <div>
            <span>Time</span>
            <b>{dur(f.seconds.p50)}</b>
            <small>up to {dur(f.seconds.p90)}</small>
          </div>
        )}
      </div>
      {f.accept_rate !== null && (
        <div className="fc-accept">
          <span className="fc-bar" aria-hidden="true"><i style={{ width: `${f.accept_rate * 100}%` }} /></span>
          <span className="small">{Math.round(f.accept_rate * 100)}% were accepted</span>
        </div>
      )}
      {(risk.tokens || risk.cost) && (
        <p className="fc-warn small" role="status">
          Your {risk.tokens && risk.cost ? "token budget and cost cap are" : risk.tokens ? "token budget is" : "cost cap is"} below what half of
          these needed — the run will likely stop on budget.
        </p>
      )}
    </div>
  );
}

/* ---------- 3. regression watch ---------- */

export function WatchCard({ taskId, status, canEdit }: { taskId: string; status: string; canEdit: boolean }) {
  const data = useAsync(() => api.get<WatchStatus>(`/tasks/${taskId}/watch`), [taskId]);
  const [busy, setBusy] = useState(false);
  const w = data.data?.watch;
  const accepted = status === "COMPLETED";
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      toast(ok, "ok");
      data.reload();
    } catch (e) {
      toast(message(e), "bad");
    } finally {
      setBusy(false);
    }
  };
  const result = w?.last_result || "";
  return (
    <Card title="Regression watch">
      <div className={`watch${w?.active ? " on" : ""} r-${result || "none"}`}>
        <span className="watch-eye" aria-hidden="true"><i /></span>
        <div className="watch-text">
          {!accepted ? (
            <p className="muted small">Once this task is accepted, LoopForge can re-run it on a schedule and tell you the moment it stops passing.</p>
          ) : w?.active ? (
            <>
              <strong>Watching · {w.interval_hours === 24 ? "daily" : "weekly"}</strong>
              <span className="muted small">Next check {new Date(w.next_run_at + "Z").toLocaleString()}</span>
            </>
          ) : (
            <>
              <strong>Not watched</strong>
              <span className="muted small">Re-run this accepted task regularly and get alerted if it regresses.</span>
            </>
          )}
          {result && (
            <span className={`badge ${result === "passing" ? "ok" : result === "regressed" ? "bad" : "info"}`} data-testid="watch-result">
              last check: {result}
            </span>
          )}
        </div>
        {accepted && canEdit && (
          <div className="row watch-actions">
            <div className="seg" role="group" aria-label="Check how often">
              {([24, 168] as const).map((h) => (
                <button
                  key={h}
                  type="button"
                  className={w?.active && w.interval_hours === h ? "on" : ""}
                  disabled={busy}
                  onClick={() => void act(() => api.put(`/tasks/${taskId}/watch`, { interval_hours: h, active: true }), h === 24 ? "Watching daily" : "Watching weekly")}
                >
                  {h === 24 ? "Daily" : "Weekly"}
                </button>
              ))}
            </div>
            {w?.active && <button type="button" disabled={busy} onClick={() => void act(() => api.delete(`/tasks/${taskId}/watch`), "Stopped watching")}>Stop</button>}
            <button type="button" className="primary" disabled={busy} onClick={() => void act(() => api.post(`/tasks/${taskId}/rerun`), "Re-run started")}>Re-run now</button>
          </div>
        )}
      </div>
      {data.data && data.data.reruns.length > 0 && (
        <ol className="reruns">
          {data.data.reruns.map((r) => (
            <li key={r.id}>
              <Link to={`/tasks/${r.id}`}>{new Date(r.created_at + "Z").toLocaleString()}</Link>
              <StatusBadge status={r.status} />
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

/* ---------- 5. A/B ---------- */

const AGENTS = ["Repair", "Builder", "Planner", "Reviewer", "Documentation"] as const;

export function ExperimentCard({ taskId, canRun }: { taskId: string; canRun: boolean }) {
  const navigate = useNavigate();
  const [agent, setAgent] = useState<(typeof AGENTS)[number]>("Repair");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    setBusy(true);
    try {
      const exp = await api.post<Experiment>(`/tasks/${taskId}/experiments`, { agent, model_a: a.trim(), model_b: b.trim() });
      toast("A/B test started — two runs are going", "ok");
      navigate(`/compare?experiment=${exp.experiment}`);
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  };
  if (!canRun) return null;
  return (
    <Card title="A/B test a model">
      <form className="ab-form" onSubmit={(e) => void submit(e)}>
        <p className="muted small">
          Run this task twice from scratch, changing only the model one agent uses, then compare quality, rounds, tokens and cost side by side.
        </p>
        <div className="ab-row">
          <label>
            Agent
            <select value={agent} onChange={(e) => setAgent(e.target.value as (typeof AGENTS)[number])}>
              {AGENTS.map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <label>
            Model A
            <input required value={a} pattern="[A-Za-z0-9._:/\-]{1,80}" placeholder="e.g. gpt-4o-mini" onChange={(e) => setA(e.target.value)} />
          </label>
          <span className="ab-vs" aria-hidden="true">vs</span>
          <label>
            Model B
            <input required value={b} pattern="[A-Za-z0-9._:/\-]{1,80}" placeholder="e.g. gpt-4o" onChange={(e) => setB(e.target.value)} />
          </label>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? "Starting…" : "Start A/B test"}</button>
      </form>
    </Card>
  );
}

export type Metric = "quality" | "iterations" | "tokens" | "cost" | "seconds";
export const METRICS: { id: Metric; label: string; better: "high" | "low" }[] = [
  { id: "quality", label: "Quality", better: "high" },
  { id: "iterations", label: "Rounds", better: "low" },
  { id: "tokens", label: "Tokens", better: "low" },
  { id: "cost", label: "Cost", better: "low" },
  { id: "seconds", label: "Time", better: "low" },
];

/** Per-metric winner index (or null for a tie/missing), plus an overall winner. Acceptance beats everything. */
export function verdict(vs: Variant[]): { metric: Record<Metric, number | null>; overall: number | null } {
  const metric = {} as Record<Metric, number | null>;
  const wins = vs.map(() => 0);
  for (const m of METRICS) {
    const vals = vs.map((v) => v[m.id]);
    if (vals.some((x) => x === null || x === undefined) || new Set(vals).size === 1) {
      metric[m.id] = null;
      continue;
    }
    const nums = vals as number[];
    const best = m.better === "high" ? Math.max(...nums) : Math.min(...nums);
    metric[m.id] = nums.indexOf(best);
    wins[metric[m.id]!] += 1;
  }
  const accepted = vs.map((v) => v.status === "COMPLETED");
  let overall: number | null = null;
  if (accepted.filter(Boolean).length === 1) overall = accepted.indexOf(true);
  else if (Math.max(...wins) > Math.min(...wins)) overall = wins.indexOf(Math.max(...wins));
  return { metric, overall };
}

/* ---------- 4. task chains ---------- */

export function ChainPicker({ value, onChange }: { value: string | null; onChange: (id: string | null, t?: Task) => void }) {
  const [q, setQ] = useState("");
  const tasks = useAsync(() => api.get<Task[]>("/tasks", { limit: 200, order: "desc" }), []);
  const done = useMemo(
    () => (Array.isArray(tasks.data) ? tasks.data : []).filter((t) => t && t.status === "COMPLETED"),
    [tasks.data],
  );
  const shown = done.filter((t) => t.requirement.toLowerCase().includes(q.trim().toLowerCase())).slice(0, 8);
  const picked = done.find((t) => t.id === value);
  return (
    <div className="chain" aria-label="Continue from a task">
      {picked ? (
        <div className="chain-picked">
          <span className="chain-link" aria-hidden="true">⛓</span>
          <div>
            <span className="muted small">Continuing from</span>
            <strong>{picked.requirement}</strong>
          </div>
          <button type="button" className="link" onClick={() => onChange(null)}>Change</button>
        </div>
      ) : (
        <>
          <input value={q} placeholder="Search your accepted tasks…" aria-label="Search accepted tasks" onChange={(e) => setQ(e.target.value)} />
          {done.length === 0 && <p className="muted small">No accepted tasks yet — finish one first, then build on it here.</p>}
          <ul className="chain-list">
            {shown.map((t) => (
              <li key={t.id}>
                <button type="button" onClick={() => onChange(t.id, t)}>
                  <span className="chain-dot" aria-hidden="true" />
                  <span className="chain-req">{t.requirement}</span>
                  <small className="muted">{t.current_iteration} rounds</small>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="muted small">The new task starts from that task&apos;s accepted code — the loop extends it instead of starting over.</p>
    </div>
  );
}
