import { Link } from "react-router";
import type { Task } from "../api/types";
import { isTerminal } from "../api/types";

/* ---------- pure helpers (unit-tested) ---------- */

export const STATUS_TONE: Record<string, string> = {
  COMPLETED: "var(--ok)",
  FAILED: "var(--bad)",
  ESCALATED: "var(--warn)",
  CANCELLED: "var(--muted)",
  PENDING: "#6b7280",
  AWAITING_APPROVAL: "var(--ember)",
};
const RUNNING_TONE = "var(--primary)";

export interface Slice {
  key: string;
  value: number;
  start: number; // fraction 0..1
  end: number;
  color: string;
}

/** Donut slices from a status → count map; zero counts are dropped, order is largest first. */
export function donutSlices(counts: Record<string, number>): Slice[] {
  const entries = Object.entries(counts).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((n, [, v]) => n + v, 0);
  let at = 0;
  return entries.map(([key, value]) => {
    const start = at;
    at += total ? value / total : 0;
    return { key, value, start, end: at, color: STATUS_TONE[key] ?? RUNNING_TONE };
  });
}

/** Task counts per day for the last `weeks` weeks, oldest first, as columns of 7 days. */
export function heatmap(dates: string[], weeks = 12, today = new Date()): { day: string; count: number }[][] {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const startOffset = weeks * 7 - 1 - (6 - end.getDay()); // the grid ends on this week's Saturday
  const key = (d: Date) => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
  const counts = new Map<string, number>();
  for (const iso of dates) {
    const d = new Date(iso);
    if (!Number.isNaN(d.getTime())) counts.set(key(d), (counts.get(key(d)) ?? 0) + 1);
  }
  const cols: { day: string; count: number }[][] = [];
  for (let w = 0; w < weeks; w++) {
    const col = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(end);
      d.setDate(end.getDate() - startOffset + w * 7 + i);
      col.push({ day: d.toDateString(), count: d > end ? -1 : counts.get(key(d)) ?? 0 });
    }
    cols.push(col);
  }
  return cols;
}

export const STAGES = ["PLANNING", "GENERATING", "TESTING", "REVIEWING", "REPAIRING"] as const;
const STAGE_OF: Record<string, number> = { PLANNING: 0, GENERATING: 1, EXECUTING: 2, TESTING: 2, REVIEWING: 3, REPAIRING: 4, AWAITING_APPROVAL: 0 };

export const isRunning = (t: Task) => !isTerminal(t.status) && t.status !== "PENDING";

/* ---------- components ---------- */

const label = (s: string) => s.replace(/_/g, " ").toLowerCase();

export function StatusDonut({ counts }: { counts: Record<string, number> }) {
  const slices = donutSlices(counts);
  const total = slices.reduce((n, s) => n + s.value, 0);
  const r = 38;
  const c = 2 * Math.PI * r;
  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 100 100" className="donut" role="img" aria-label={`${total} tasks by status`}>
        <circle cx="50" cy="50" r={r} className="donut-track" />
        {slices.map((s, i) => (
          <circle
            key={s.key}
            cx="50"
            cy="50"
            r={r}
            className="donut-seg"
            stroke={s.color}
            strokeDasharray={`${Math.max(0, (s.end - s.start) * c - (slices.length > 1 ? 1.5 : 0))} ${c}`}
            strokeDashoffset={-s.start * c}
            style={{ animationDelay: `${i * 0.12}s` }}
          />
        ))}
        <text x="50" y="49" className="donut-total">{total}</text>
        <text x="50" y="61" className="donut-cap">tasks</text>
      </svg>
      <ul className="legend">
        {slices.length === 0 && <li className="muted">No tasks yet</li>}
        {slices.map((s) => (
          <li key={s.key}>
            <i style={{ background: s.color }} />
            <span>{label(s.key)}</span>
            <b>{s.value}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ActivityHeatmap({ dates }: { dates: string[] }) {
  const cols = heatmap(dates);
  const max = Math.max(1, ...cols.flat().map((c) => c.count));
  const total = cols.flat().reduce((n, c) => n + Math.max(0, c.count), 0);
  return (
    <div className="heat-wrap">
      <div className="heat" role="img" aria-label={`${total} tasks created in the last 12 weeks`}>
        {cols.map((col, w) => (
          <div key={w} className="heat-col">
            {col.map((cell) => (
              <i
                key={cell.day}
                title={cell.count >= 0 ? `${cell.count} task${cell.count === 1 ? "" : "s"} · ${cell.day}` : undefined}
                className={cell.count < 0 ? "future" : `l${cell.count === 0 ? 0 : Math.ceil((cell.count / max) * 4)}`}
                style={{ animationDelay: `${w * 0.03}s` }}
              />
            ))}
          </div>
        ))}
      </div>
      <div className="heat-foot muted small">
        <span>{total} in 12 weeks</span>
        <span className="heat-scale">less <i className="l0" /><i className="l1" /><i className="l2" /><i className="l3" /><i className="l4" /> more</span>
      </div>
    </div>
  );
}

export function RunningNow({ tasks }: { tasks: Task[] }) {
  const running = tasks.filter(isRunning);
  if (running.length === 0) {
    return (
      <div className="running-empty">
        <span className="pulse-ring" aria-hidden="true" />
        <div>
          <strong>No loops running</strong>
          <p className="muted small">Start a task and it will appear here live.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="running-list">
      {running.slice(0, 4).map((t) => {
        const stage = STAGE_OF[t.status] ?? 0;
        return (
          <Link key={t.id} to={`/tasks/${t.id}`} className="run-card">
            <div className="run-top">
              <span className="live-dot" aria-hidden="true" />
              <span className="run-status">{label(t.status)}</span>
              <span className="muted small">it. {t.current_iteration}/{t.max_iterations}</span>
            </div>
            <p className="run-req">{t.requirement}</p>
            <ol className="stepper" aria-label={`Stage: ${label(t.status)}`}>
              {STAGES.map((s, i) => (
                <li key={s} className={i < stage ? "done" : i === stage ? "now" : ""}>
                  <span>{label(s)}</span>
                </li>
              ))}
            </ol>
          </Link>
        );
      })}
    </div>
  );
}

export function QuickStart() {
  return (
    <Link to="/tasks/new" className="quickstart">
      <span className="qs-glow" aria-hidden="true" />
      <span className="qs-kicker">New loop</span>
      <span className="qs-prompt">Describe what to build<span className="qs-caret" aria-hidden="true" /></span>
      <span className="qs-hint muted small">Plain English in → tested, reviewed code out</span>
    </Link>
  );
}
