/* Building blocks for the New task "launch composer". Pure helpers are unit-tested. */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { Task } from "../api/types";
import { forecast, rankSimilar } from "../lib/similarity";

/** Past tasks that look like what is being typed, and what they suggest about this run. */
export function SimilarTasks({ requirement, onReuse }: { requirement: string; onReuse: (t: Task) => void }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [debounced, setDebounced] = useState(requirement);
  useEffect(() => {
    api
      .get<Task[]>("/tasks", { limit: 200, order: "desc" })
      .then((t) =>
        Array.isArray(t) &&
        setTasks(t.filter((x) => x && typeof x.id === "string" && typeof x.requirement === "string" && typeof x.status === "string")),
      )
      .catch(() => undefined); // a convenience: the form works without it
  }, []);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(requirement), 300);
    return () => window.clearTimeout(t);
  }, [requirement]);
  const similar = useMemo(
    () => rankSimilar(debounced, tasks.map((t) => ({ item: t, text: t.requirement })), 3),
    [debounced, tasks],
  );
  if (similar.length === 0) return null;
  const f = forecast(similar.map((s) => s.item));
  return (
    <div className="similar" aria-label="Similar past tasks">
      <div className="sim-head">
        <span className="pv-kicker">Seen something like this</span>
        {f.basis > 0 && (
          <span className="sim-forecast">
            {f.acceptRate !== null && <b className={f.acceptRate >= 0.5 ? "ok-text" : "error"}>{Math.round(f.acceptRate * 100)}% accepted</b>}
            {f.avgIterations !== null && <span className="muted small"> · ~{f.avgIterations.toFixed(1)} rounds</span>}
          </span>
        )}
      </div>
      <ul>
        {similar.map(({ item, score }) => (
          <li key={item.id} className="sim-item">
            <span className="sim-match" aria-label={`${Math.round(score * 100)}% similar`}>{Math.round(score * 100)}%</span>
            <Link to={`/tasks/${item.id}`} className="sim-req">{item.requirement}</Link>
            <span className={`sim-st st-${item.status}`}>{item.status.toLowerCase().replace(/_/g, " ")}</span>
            <button type="button" className="link small" onClick={() => onReuse(item)}>Reuse</button>
          </li>
        ))}
      </ul>
      {f.basis > 0 && <p className="muted small sim-note">Forecast from {f.basis} finished similar task{f.basis === 1 ? "" : "s"}.</p>}
    </div>
  );
}

export interface Quality {
  score: number; // 0..100
  level: "empty" | "vague" | "okay" | "specific";
  tips: string[];
}

/** A rough, local estimate of how well-specified a requirement is. Advisory only; never blocks submit. */
export function promptQuality(requirement: string, criteria: string[]): Quality {
  const text = requirement.trim();
  if (!text) return { score: 0, level: "empty", tips: ["Describe what you want built."] };
  const tips: string[] = [];
  let score = 0;
  const words = text.split(/\s+/).length;
  score += Math.min(35, words * 2.2);
  if (words < 8) tips.push("Add a little more detail: inputs, outputs, edge cases.");
  if (/\btest|pytest|jest|unit|edge.?case/i.test(text)) score += 20;
  else tips.push("Say how it should be tested.");
  if (/\b(api|endpoint|get|post|put|delete|cli|function|class|route|command)\b/i.test(text)) score += 15;
  else tips.push("Name the interface: an API, CLI, or function.");
  if (/\b(return|status|error|invalid|validate|should|must)\b/i.test(text)) score += 10;
  if (criteria.length > 0) score += Math.min(20, criteria.length * 7);
  else tips.push("Optional: list acceptance criteria below.");
  score = Math.round(Math.min(100, score));
  return { score, level: score >= 70 ? "specific" : score >= 40 ? "okay" : "vague", tips: tips.slice(0, 2) };
}

export const parseCriteria = (text: string) => text.split("\n").map((c) => c.trim()).filter(Boolean);

export const IDEAS = [
  { icon: "⇄", label: "URL shortener", name: "url_shortener", blurb: "FastAPI · redirects · tests",
    text: "Build a FastAPI URL shortener: POST /links creates a short code, GET /{code} redirects, with unit tests for both." },
  { icon: "✎", label: "Slugify util", name: "slugify", blurb: "Pure function · edge cases",
    text: "Write a slugify(text) function that lowercases, strips accents and joins words with hyphens, with edge-case tests." },
  { icon: "☑", label: "Todo API", name: "todo_api", blurb: "CRUD endpoints · tests",
    text: "Build a todo REST API with create, list, update, delete and mark-done endpoints, plus tests for each." },
  { icon: "∑", label: "CSV stats", name: "csv_stats", blurb: "CLI · mean / median / max",
    text: "Write a CLI that reads a CSV file and prints the mean, median and max of a chosen numeric column, with tests." },
];

export const LANGS = [
  { id: "python", label: "Python", hint: "FastAPI · pytest" },
  { id: "javascript", label: "JS / TS", hint: "Node · Jest" },
  { id: "go", label: "Go", hint: "stdlib · experimental" },
] as const;

export const SOURCES = [
  { id: "none", label: "New project", hint: "Start from scratch", icon: "✦" },
  { id: "zip", label: "Upload zip", hint: "Existing repository", icon: "⇪" },
  { id: "git", label: "Git URL", hint: "Public https repo", icon: "⎇" },
  { id: "task", label: "Continue a task", hint: "Build on accepted code", icon: "⛓" },
] as const;

/** A tile that mirrors a <select>; the select stays the source of truth for forms and tests. */
export function Tile({ on, onClick, title, hint, mark, tone }: { on: boolean; onClick: () => void; title: string; hint: string; mark: string; tone?: string }) {
  return (
    <button type="button" className={`tile${on ? " on" : ""}`} aria-pressed={on} onClick={onClick}>
      <span className={`tile-mark ${tone ?? ""}`} aria-hidden="true">{mark}</span>
      <span className="tile-text">
        <strong>{title}</strong>
        <small>{hint}</small>
      </span>
    </button>
  );
}

export function Section({ n, title, sub, children }: { n: number; title: string; sub: string; children: React.ReactNode }) {
  return (
    <section className="cmp-section">
      <header>
        <span className="cmp-n" aria-hidden="true">{n}</span>
        <div>
          <h2>{title}</h2>
          <p className="muted small">{sub}</p>
        </div>
      </header>
      <div className="cmp-body">{children}</div>
    </section>
  );
}
