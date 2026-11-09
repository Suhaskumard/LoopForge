import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { PipelineT, Project } from "../api/types";
import { useAuth } from "../auth";
import { IconFlow } from "../components/icons";
import { toast } from "../components/Toast";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

interface Draft {
  requirement: string;
  criteria: string;
  rounds: number;
}
const blank = (): Draft => ({ requirement: "", criteria: "", rounds: 5 });

const STARTERS: { name: string; steps: string[] }[] = [
  {
    name: "API → client → docs",
    steps: [
      "Build a FastAPI todo service with create, list, update, delete endpoints and tests.",
      "Add a small Python client module for the todo API with typed methods and tests.",
      "Add usage documentation and example scripts for the client, with a smoke test.",
    ],
  },
  {
    name: "Core → validation → errors",
    steps: [
      "Write a slugify(text) function with tests for basic words.",
      "Extend slugify to strip accents and collapse repeated separators, with edge-case tests.",
      "Make invalid input raise clear ValueErrors and test every error path.",
    ],
  },
];

/** Validate the builder before sending: 2-10 steps, each with a real requirement. */
export function draftProblems(name: string, steps: Draft[]): string[] {
  const out: string[] = [];
  if (!name.trim()) out.push("Give the pipeline a name.");
  if (steps.length < 2) out.push("A pipeline needs at least 2 steps.");
  if (steps.length > 10) out.push("At most 10 steps.");
  steps.forEach((s, i) => {
    if (s.requirement.trim().length < 5) out.push(`Step ${i + 1} needs a requirement.`);
  });
  return out;
}

function Builder({ onCreated }: { onCreated: (p: PipelineT) => void }) {
  const [name, setName] = useState("");
  const [language, setLanguage] = useState<"python" | "javascript" | "go">("python");
  const [steps, setSteps] = useState<Draft[]>([blank(), blank()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const problems = draftProblems(name, steps);
  const update = (i: number, patch: Partial<Draft>) => setSteps((s) => s.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  const move = (i: number, d: -1 | 1) =>
    setSteps((s) => {
      const j = i + d;
      if (j < 0 || j >= s.length) return s;
      const next = [...s];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (problems.length) return setError(problems[0]);
    setBusy(true);
    setError(undefined);
    try {
      const project = await api.post<Project>("/projects", { name: name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 60) || "pipeline", language });
      const p = await api.post<PipelineT>("/pipelines", {
        project_id: project.id,
        name: name.trim(),
        steps: steps.map((s) => ({
          requirement: s.requirement.trim(),
          acceptance_criteria: s.criteria.split("\n").map((c) => c.trim()).filter(Boolean),
          max_iterations: s.rounds,
        })),
      });
      toast("Pipeline created — start it when you are ready", "ok");
      onCreated(p);
      setName("");
      setSteps([blank(), blank()]);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="New pipeline">
      <form className="pl-builder" onSubmit={(e) => void submit(e)}>
        <div className="row">
          <label className="grow">
            Pipeline name
            <input value={name} maxLength={120} placeholder="e.g. API then client" onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Language
            <select value={language} onChange={(e) => setLanguage(e.target.value as typeof language)}>
              <option value="python">Python</option>
              <option value="javascript">JavaScript / TypeScript</option>
              <option value="go">Go</option>
            </select>
          </label>
        </div>
        <div className="pl-starters">
          <span className="muted small">Start from an example:</span>
          {STARTERS.map((s) => (
            <button key={s.name} type="button" className="chip" onClick={() => { setName(s.name); setSteps(s.steps.map((r) => ({ ...blank(), requirement: r }))); }}>
              {s.name}
            </button>
          ))}
        </div>
        <ol className="pl-steps">
          {steps.map((s, i) => (
            <li key={i} className="pl-step-edit">
              <span className="pl-n" aria-hidden="true">{i + 1}</span>
              <div className="pl-step-fields">
                <label>
                  Step {i + 1} requirement
                  <textarea rows={2} value={s.requirement} onChange={(e) => update(i, { requirement: e.target.value })} placeholder={i === 0 ? "What to build first…" : "What to add on top of the previous step…"} />
                </label>
                <div className="row">
                  <label className="grow">
                    Acceptance criteria <span className="muted small">(one per line, optional)</span>
                    <textarea rows={1} value={s.criteria} onChange={(e) => update(i, { criteria: e.target.value })} />
                  </label>
                  <label>
                    Rounds
                    <input type="number" min={1} max={20} value={s.rounds} onChange={(e) => update(i, { rounds: Number(e.target.value) })} />
                  </label>
                </div>
              </div>
              <div className="pl-step-tools">
                <button type="button" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move step ${i + 1} up`}>↑</button>
                <button type="button" onClick={() => move(i, 1)} disabled={i === steps.length - 1} aria-label={`Move step ${i + 1} down`}>↓</button>
                <button type="button" onClick={() => setSteps((x) => x.filter((_, k) => k !== i))} disabled={steps.length <= 2} aria-label={`Remove step ${i + 1}`}>×</button>
              </div>
            </li>
          ))}
        </ol>
        <div className="row">
          <button type="button" disabled={steps.length >= 10} onClick={() => setSteps((x) => [...x, blank()])}>Add step</button>
          <button className="primary" disabled={busy}>{busy ? "Creating…" : "Create pipeline"}</button>
          <span className="muted small">Each step starts from the previous step&apos;s accepted code.</span>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
    </Card>
  );
}

function Track({ p }: { p: PipelineT }) {
  return (
    <ol className="pl-track" aria-label={`${p.name} steps`}>
      {p.steps.map((s) => (
        <li key={s.id} className={`pl-stage ${s.status}`}>
          <span className="pl-dot" aria-hidden="true">{s.status === "accepted" ? "✓" : s.status === "failed" ? "✕" : s.position + 1}</span>
          <span className="pl-stage-text">
            {s.task_id ? <Link to={`/tasks/${s.task_id}`}>{s.requirement}</Link> : <span>{s.requirement}</span>}
            <small className="muted">{s.task_status ? s.task_status.toLowerCase().replace(/_/g, " ") : "waiting"}</small>
          </span>
        </li>
      ))}
    </ol>
  );
}

export function Pipelines() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const list = useAsync(() => api.get<PipelineT[]>("/pipelines", { limit: 50 }), []);
  const [busy, setBusy] = useState<string | null>(null);
  const live = (list.data ?? []).some((p) => p.status === "running");
  const reload = list.reload;
  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(() => reload(), 5000); // follow running pipelines
    return () => window.clearInterval(t);
  }, [live, reload]);

  const act = async (p: PipelineT, action: "start" | "pause" | "resume") => {
    setBusy(p.id + action);
    try {
      await api.post(`/pipelines/${p.id}/${action}`);
      toast(action === "start" ? "Pipeline started" : action === "pause" ? "Pipeline will pause after this step" : "Pipeline resumed", "ok");
      list.reload();
    } catch (e) {
      toast(message(e), "bad");
    } finally {
      setBusy(null);
    }
  };
  const focus = params.get("id");

  return (
    <>
      <PageHeader icon={<IconFlow />} title="Pipelines" sub="Chain tasks into a pipeline: each accepted step automatically starts the next one from its code." />
      {can("developer") && <Builder onCreated={(p) => { list.reload(); setParams({ id: p.id }); }} />}
      <Card title="Your pipelines">
        {list.error && <ErrorBox error={list.error} />}
        {list.loading && !list.data && <Loading what="Loading pipelines" />}
        {list.data && list.data.length === 0 && <Empty><span className="empty-art" aria-hidden="true">⛓</span>No pipelines yet.</Empty>}
        <ul className="pl-list">
          {list.data?.map((p) => (
            <li key={p.id} className={`pl-card ${p.status}${focus === p.id ? " focus" : ""}`}>
              <header>
                <strong>{p.name}</strong>
                <StatusBadge status={p.status} />
                <span className="muted small">{p.steps.filter((s) => s.status === "accepted").length}/{p.steps.length} accepted</span>
                {can("developer") && (
                  <span className="row pl-actions">
                    {p.status === "draft" && <button type="button" className="primary" disabled={busy !== null} onClick={() => void act(p, "start")}>Start</button>}
                    {p.status === "running" && <button type="button" disabled={busy !== null} onClick={() => void act(p, "pause")}>Pause</button>}
                    {(p.status === "paused" || p.status === "failed") && <button type="button" className="primary" disabled={busy !== null} onClick={() => void act(p, "resume")}>Resume</button>}
                  </span>
                )}
              </header>
              <Track p={p} />
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
