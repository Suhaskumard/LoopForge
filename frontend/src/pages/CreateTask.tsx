import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import type { Project, Task, Template } from "../api/types";
import { Card } from "../components/ui";

export const DEMO_REQUIREMENT =
  "Build an employee management API with authentication, CRUD and unit tests.";

/** Screen 2 — Task Creation: creates a project + task, then starts the loop. */
export function CreateTask() {
  const navigate = useNavigate();
  const [name, setName] = useState("employee_management");
  const [requirement, setRequirement] = useState(DEMO_REQUIREMENT);
  const [criteria, setCriteria] = useState("");
  const [maxIterations, setMaxIterations] = useState(5);
  const [tokenBudget, setTokenBudget] = useState("");
  const [maxCost, setMaxCost] = useState("");
  const [planApproval, setPlanApproval] = useState(false);
  const [language, setLanguage] = useState<"python" | "javascript">("python");
  const [sourceType, setSourceType] = useState<"none" | "zip" | "git">("none");
  const [gitUrl, setGitUrl] = useState("");
  const [zip, setZip] = useState<File | null>(null);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const [templates, setTemplates] = useState<Template[]>([]);
  useEffect(() => {
    api
      .get<Template[]>("/templates")
      .then((t) => Array.isArray(t) && setTemplates(t))
      .catch(() => undefined); // templates are a convenience; the form works without them
  }, []);
  const applyTemplate = (id: string) => {
    const t = templates.find((x) => x.id === id);
    if (!t) return;
    setName(t.id.replace(/-/g, "_"));
    setRequirement(t.requirement);
    setCriteria(t.acceptance_criteria.join("\n"));
    setLanguage(t.language);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      if (sourceType === "zip" && !zip) throw new Error("Choose a .zip file of the repository");
      const project = await api.post<Project>("/projects", { name, language });
      const task = await api.post<Task>("/tasks", {
        project_id: project.id,
        requirement,
        max_iterations: maxIterations,
        acceptance_criteria: criteria.split("\n").map((c) => c.trim()).filter(Boolean),
        token_budget: tokenBudget ? Number(tokenBudget) : undefined,
        max_cost: maxCost ? Number(maxCost) : undefined,
        require_plan_approval: planApproval,
        source_type: sourceType,
        git_url: sourceType === "git" ? gitUrl.trim() : undefined,
      });
      if (sourceType === "zip" && zip) await api.upload<Task>(`/tasks/${task.id}/source`, zip);
      await api.post(`/tasks/${task.id}/start`);
      navigate(`/tasks/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the task");
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-head"><h1>New task</h1></header>
      <Card>
        <form className="form" onSubmit={(e) => void submit(e)}>
          {templates.length > 0 && (
            <label>
              Start from a template
              <select aria-label="Template" defaultValue="" onChange={(e) => applyTemplate(e.target.value)}>
                <option value="">None — write my own</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name} — {t.description}</option>
                ))}
              </select>
            </label>
          )}
          <label>
            Project name
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
          </label>
          <label>
            Natural-language requirement
            <textarea value={requirement} onChange={(e) => setRequirement(e.target.value)} rows={5} required />
          </label>
          <div className="row">
            <label>
              Language
              <select
                value={language}
                aria-label="Language"
                onChange={(e) => setLanguage(e.target.value as "python" | "javascript")}
              >
                <option value="python">Python (FastAPI, pytest)</option>
                <option value="javascript">JavaScript / TypeScript (Jest)</option>
              </select>
            </label>
            <label>
              Iteration limit
              <input type="number" min={1} max={20} value={maxIterations} onChange={(e) => setMaxIterations(Number(e.target.value))} />
            </label>
          </div>
          <label>
            Starting point
            <select
              value={sourceType}
              aria-label="Starting point"
              onChange={(e) => setSourceType(e.target.value as "none" | "zip" | "git")}
            >
              <option value="none">New project</option>
              <option value="zip">Existing repository (zip upload)</option>
              <option value="git">Existing repository (public https git URL)</option>
            </select>
          </label>
          {sourceType === "zip" && (
            <label>
              Repository zip
              <input
                type="file"
                accept=".zip,application/zip"
                aria-label="Repository zip"
                onChange={(e) => setZip(e.target.files?.[0] ?? null)}
              />
            </label>
          )}
          {sourceType === "git" && (
            <label>
              Git URL
              <input
                type="url"
                value={gitUrl}
                placeholder="https://github.com/owner/repo"
                aria-label="Git URL"
                onChange={(e) => setGitUrl(e.target.value)}
                required
              />
            </label>
          )}
          {sourceType !== "none" && (
            <p className="muted small">
              The repository is treated as untrusted: it is never executed outside the sandbox, only text source
              files are used, and files containing credentials are excluded and never sent to a model.
            </p>
          )}
          <label>
            Acceptance criteria <span className="muted small">(one per line, optional — the Planner adds its own)</span>
            <textarea value={criteria} onChange={(e) => setCriteria(e.target.value)} rows={4} />
          </label>
          <div className="row">
            <label>
              Token budget <span className="muted small">(optional, 1000 or more)</span>
              <input
                type="number"
                min={1000}
                step={1000}
                value={tokenBudget}
                placeholder="server default"
                onChange={(e) => setTokenBudget(e.target.value)}
              />
            </label>
            <label>
              Cost cap, USD <span className="muted small">(optional, an estimate)</span>
              <input
                type="number"
                min={0.001}
                step={0.01}
                value={maxCost}
                placeholder="none"
                onChange={(e) => setMaxCost(e.target.value)}
              />
            </label>
          </div>
          <label className="check">
            <input type="checkbox" checked={planApproval} onChange={(e) => setPlanApproval(e.target.checked)} />
            Pause for my approval after planning, before any code is written
          </label>
          <p className="muted small">
            Budgets are enforced by the server: reaching one escalates the task instead of spending more. A repair
            that touches many files always waits for your approval.
          </p>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary" disabled={busy}>{busy ? "Starting…" : "Create and start"}</button>
        </form>
      </Card>
    </>
  );
}
