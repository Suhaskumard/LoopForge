import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react";
import { useEffect, useState } from "react";
import type { LiveEvent } from "../api/types";
import type { LiveState } from "../lib/events";
import { prefersReducedMotion } from "./Confetti";

/* ---------- pure helpers (unit-tested) ---------- */

/** Seconds between the first event and the terminal event (or `now` while running). */
export function elapsedSeconds(timeline: LiveEvent[], terminal: string | null, now = Date.now()): number {
  const stamps = timeline.map((e) => Date.parse(e.timestamp)).filter((t) => !Number.isNaN(t));
  if (stamps.length === 0) return 0;
  const start = Math.min(...stamps);
  const end = terminal ? Math.max(...stamps) : now;
  return Math.max(0, Math.round((end - start) / 1000));
}

export const clock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

export function ago(iso: string, now = Date.now()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

/** Consecutive runs of events that share an iteration; events without one join the current group. */
export function groupByIteration(timeline: LiveEvent[]): { iteration: number | null; events: LiveEvent[] }[] {
  const groups: { iteration: number | null; events: LiveEvent[] }[] = [];
  for (const e of timeline) {
    const it = typeof e.iteration === "number" ? e.iteration : null;
    const last = groups[groups.length - 1];
    if (last && (it === null || last.iteration === it || last.iteration === null)) {
      if (last.iteration === null && it !== null) last.iteration = it;
      last.events.push(e);
    } else groups.push({ iteration: it, events: [e] });
  }
  return groups;
}

export function glyph(e: LiveEvent): string {
  if (e.event === "task_completed" || e.event === "iteration_completed") return "✓";
  if (e.event === "task_failed" || e.event === "task_cancelled") return "✕";
  if (e.event === "escalated") return "⚑";
  if (e.event === "retry_scheduled") return "↺";
  if (e.event === "tests_completed") return (e.tests_failed ?? 0) > 0 ? "✕" : "✓";
  if (e.event === "agent_completed") return e.status === "success" ? "✓" : "✕";
  if (e.event.endsWith("_started")) return "▶";
  return "•";
}

/** Re-render every second while `active`, so timers tick. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [active]);
  return now;
}

/* ---------- graph edge: data packets travel along active edges ---------- */

export function PacketEdge(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, animated, label, markerEnd, style } = props;
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const moving = animated && !prefersReducedMotion();
  return (
    <>
      <BaseEdge path={path} label={label} labelX={labelX} labelY={labelY} markerEnd={markerEnd} style={style} />
      {moving &&
        [0, 0.45, 0.9].map((begin) => (
          <circle key={begin} r="3.2" className="packet">
            <animateMotion dur="1.35s" repeatCount="indefinite" begin={`${begin}s`} path={path} />
          </circle>
        ))}
    </>
  );
}

/* ---------- mission header ---------- */

type Mood = "idle" | "running" | "ok" | "bad";

export function Reactor({
  live,
  maxIterations,
  status,
  asOf,
}: {
  live: LiveState;
  maxIterations: number;
  status: string | undefined;
  asOf?: number; // replay: freeze the clock at this moment
}) {
  const running = !live.terminal && status !== "PENDING" && live.timeline.length > 0;
  const ticking = useNow(running && asOf === undefined);
  const now = asOf ?? ticking;
  const mood: Mood = live.terminal === "COMPLETED" ? "ok" : live.terminal ? "bad" : running ? "running" : "idle";
  const headline =
    mood === "ok" ? "Accepted" : mood === "bad" ? live.terminal!.toLowerCase() : live.current ?? (running ? "Deciding…" : status === "PENDING" ? "Ready to launch" : "Waiting");
  const sub =
    mood === "running" && live.current ? "is working" : mood === "ok" ? "all criteria met" : mood === "bad" ? "the loop stopped" : running ? "between agents" : "start the loop to watch it run";
  const tokens = Object.values(live.agents).reduce((n, a) => n + (a.tokens ?? 0), 0);
  const retries = live.timeline.filter((e) => e.event === "retry_scheduled").length;
  const it = Math.max(live.iteration, 0);
  const r = 26;
  const c = 2 * Math.PI * r;
  const frac = Math.min(1, it / Math.max(1, maxIterations));

  return (
    <section className={`reactor ${mood}`} aria-label="Loop status">
      <div className="core" aria-hidden="true">
        <span className="ring r1" />
        <span className="ring r2" />
        <span className="ring r3" />
        <span className="nucleus" />
      </div>
      <div className="reactor-text">
        <span className="reactor-kicker">{mood === "running" ? "Live" : mood === "ok" ? "Done" : mood === "bad" ? "Stopped" : "Standby"}</span>
        <strong key={headline} className="reactor-agent">{headline}</strong>
        <span className="muted">{sub}</span>
      </div>
      <dl className="reactor-stats">
        <div className="stat-ring">
          <svg viewBox="0 0 64 64" aria-hidden="true">
            <circle cx="32" cy="32" r={r} className="sr-track" />
            <circle cx="32" cy="32" r={r} className="sr-bar" strokeDasharray={c} strokeDashoffset={c * (1 - frac)} />
          </svg>
          <div>
            <dt>Iteration</dt>
            <dd>{it}<small>/{maxIterations}</small></dd>
          </div>
        </div>
        <div>
          <dt>Elapsed</dt>
          <dd className="mono">{clock(elapsedSeconds(live.timeline, live.terminal, now))}</dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd className="mono">{tokens.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Retries</dt>
          <dd className="mono">{retries}</dd>
        </div>
      </dl>
    </section>
  );
}

/* ---------- loop stage rail ---------- */

const RAIL: { agent: string; label: string }[] = [
  { agent: "Planner", label: "Plan" },
  { agent: "Builder", label: "Build" },
  { agent: "Verifier", label: "Verify" },
  { agent: "Reviewer", label: "Review" },
  { agent: "Decision", label: "Decide" },
];

export function StageRail({ live }: { live: LiveState }) {
  const retries = live.timeline.filter((e) => e.event === "retry_scheduled").length;
  const repairing = live.agents.Repair?.state === "running";
  return (
    <div className="rail-wrap">
      <ol className="rail" aria-label="Loop stages">
        {RAIL.map(({ agent, label }) => {
          const state =
            agent === "Decision"
              ? live.terminal === "COMPLETED"
                ? "success"
                : live.terminal
                  ? "failed"
                  : "idle"
              : live.agents[agent]?.state ?? "idle";
          return (
            <li key={agent} className={`stage ${state}`}>
              <span className="stage-dot" aria-hidden="true">{state === "success" ? "✓" : state === "failed" ? "✕" : ""}</span>
              <span className="stage-label">{label}</span>
            </li>
          );
        })}
      </ol>
      {(retries > 0 || repairing) && (
        <div className={`retry-arc${repairing ? " on" : ""}`}>
          <span aria-hidden="true">↺</span> Repair loop{retries > 0 ? ` · ${retries} retr${retries === 1 ? "y" : "ies"}` : ""}
        </div>
      )}
    </div>
  );
}

/* ---------- agent roster ---------- */

export function AgentRoster({ live }: { live: LiveState }) {
  return (
    <ul className="roster">
      {Object.entries(live.agents).map(([name, a]) => (
        <li key={name} className={`agent-chip ${a.state}`}>
          <span className="ac-dot" aria-hidden="true" />
          <strong>{name}</strong>
          <span className="muted small">{a.state === "idle" ? "idle" : a.state}{a.iteration ? ` · it.${a.iteration}` : ""}</span>
          <span className="ac-tokens mono small">{a.tokens > 0 ? `${a.tokens.toLocaleString()} tok` : "—"}</span>
        </li>
      ))}
    </ul>
  );
}

export function TestsBar({ passed, failed }: { passed: number; failed: number }) {
  const total = passed + failed;
  if (total === 0) return null;
  return (
    <span className="tests-bar" aria-hidden="true">
      <i className="pass" style={{ width: `${(passed / total) * 100}%` }} />
      <i className="fail" style={{ width: `${(failed / total) * 100}%` }} />
    </span>
  );
}
