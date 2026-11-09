import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { Project, Task, Template } from "../api/types";
import { IconRocket } from "../components/icons";
import { IDEAS, LANGS, parseCriteria, promptQuality, Section, SimilarTasks, SOURCES, Tile } from "../components/Composer";
import { ChainPicker, ForecastBlock } from "../components/Intel";

type SourceType = "none" | "zip" | "git" | "task";

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
  const [learn, setLearn] = useState(true);
  const [language, setLanguage] = useState<"python" | "javascript" | "go">("python");
  const [params] = useSearchParams();
  const [sourceType, setSourceType] = useState<SourceType>(params.has("from") ? "task" : "none");
  const [fromTask, setFromTask] = useState<string | null>(params.get("from") || null);
  const [fromProject, setFromProject] = useState<string | null>(null);
  const [gitUrl, setGitUrl] = useState("");
  const [zip, setZip] = useState<File | null>(null);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState(0);
  const [dragging, setDragging] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

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
      if (sourceType === "task" && !fromTask) throw new Error("Pick the accepted task to continue from");
      let projectId = sourceType === "task" ? fromProject : null;
      if (sourceType === "task" && fromTask && !projectId) {
        projectId = (await api.get<Task>(`/tasks/${fromTask}`)).project_id; // a chain stays in its project
      }
      if (!projectId) projectId = (await api.post<Project>("/projects", { name, language })).id;
      const task = await api.post<Task>("/tasks", {
        project_id: projectId,
        requirement,
        max_iterations: maxIterations,
        acceptance_criteria: criteria.split("\n").map((c) => c.trim()).filter(Boolean),
        token_budget: tokenBudget ? Number(tokenBudget) : undefined,
        max_cost: maxCost ? Number(maxCost) : undefined,
        require_plan_approval: planApproval,
        learn_from_task: learn ? undefined : false,
        source_type: sourceType,
        git_url: sourceType === "git" ? gitUrl.trim() : undefined,
        from_task_id: sourceType === "task" ? fromTask : undefined,
      });
      if (sourceType === "zip" && zip) await api.upload<Task>(`/tasks/${task.id}/source`, zip);
      await api.post(`/tasks/${task.id}/start`);
      navigate(`/tasks/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the task");
      setBusy(false);
    }
  };

  const criteriaList = parseCriteria(criteria);
  const quality = promptQuality(requirement, criteriaList);
  const pickIdea = (idea: (typeof IDEAS)[number]) => {
    setRequirement(idea.text);
    setName(idea.name);
    setFlash((f) => f + 1);
  };
  const sourceLabel = SOURCES.find((s) => s.id === sourceType)?.label ?? "";
  const langLabel = LANGS.find((l) => l.id === language)?.label ?? language;

  return (
    <>
      <header className="page-head cmp-hero">
        <div className="cmp-hero-mark orbit" aria-hidden="true"><span /><span /><span /><IconRocket /></div>
        <div>
          <h1>New task</h1>
          <p className="muted hero-sub">What should the loop build? Describe it — LoopForge plans, codes, tests and reviews until it passes.</p>
        </div>
      </header>

      <div className="composer">
        <form id="task-composer" ref={formRef} className="cmp-form" onSubmit={(e) => void submit(e)}>
          <div className={`prompt-stage q-${quality.level}`}>
            {templates.length > 0 && (
              <label className="tpl">
                Start from a template
                <select aria-label="Template" defaultValue="" onChange={(e) => { applyTemplate(e.target.value); setFlash((f) => f + 1); }}>
                  <option value="">None — write my own</option>
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>{t.name} — {t.description}</option>
                  ))}
                </select>
              </label>
            )}
            <label className="prompt-label">
              Natural-language requirement
              <textarea
                key={flash}
                className={`big-prompt${flash ? " flash" : ""}`}
                value={requirement}
                onChange={(e) => setRequirement(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    formRef.current?.requestSubmit();
                  }
                }}
                rows={5}
                required
                placeholder="e.g. A FastAPI service that shortens URLs, with tests…"
              />
            </label>
            <div className="quality" aria-live="polite">
              <div className="quality-bar" aria-hidden="true"><i style={{ width: `${quality.score}%` }} /></div>
              <span className="quality-level">{quality.level === "empty" ? "Waiting for an idea" : `Prompt is ${quality.level}`}</span>
              <span className="muted small">{quality.tips[0] ?? "Looks great — ready to launch."}</span>
              <kbd className="quality-kbd">Ctrl ↵</kbd>
            </div>
            <div className="ideas" aria-label="Example requirements">
              {IDEAS.map((idea) => (
                <button type="button" key={idea.label} className="idea" onClick={() => pickIdea(idea)}>
                  <span className="idea-icon" aria-hidden="true">{idea.icon}</span>
                  <strong>{idea.label}</strong>
                  <small>{idea.blurb}</small>
                </button>
              ))}
            </div>
          </div>

          <Section n={1} title="Project & stack" sub="Name it and pick the language the loop writes and tests in.">
            <label>
              Project name
              <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
            </label>
            <div className="tiles">
              {LANGS.map((l) => (
                <Tile key={l.id} on={language === l.id} onClick={() => setLanguage(l.id)} title={l.label} hint={l.hint} mark={l.label.slice(0, 2)} tone={`lang-${l.id}`} />
              ))}
            </div>
            <div className="row">
              <label>
                Language
                <select
                  value={language}
                  aria-label="Language"
                  onChange={(e) => setLanguage(e.target.value as "python" | "javascript" | "go")}
                >
                  <option value="python">Python (FastAPI, pytest)</option>
                  <option value="javascript">JavaScript / TypeScript (Jest)</option>
                  <option value="go">Go, standard library (experimental)</option>
                </select>
              </label>
              <label>
                Iteration limit
                <input type="number" min={1} max={20} value={maxIterations} onChange={(e) => setMaxIterations(Number(e.target.value))} />
              </label>
            </div>
            <div className="iter-track" aria-hidden="true">
              {Array.from({ length: 20 }, (_, i) => <i key={i} className={i < maxIterations ? "on" : ""} />)}
              <span className="muted small">up to {maxIterations} build → test → repair rounds</span>
            </div>
          </Section>

          <Section n={2} title="Starting point" sub="Build fresh, or let the loop work on an existing repository.">
            <div className="tiles">
              {SOURCES.map((s) => (
                <Tile key={s.id} on={sourceType === s.id} onClick={() => setSourceType(s.id)} title={s.label} hint={s.hint} mark={s.icon} />
              ))}
            </div>
            <label>
              Starting point
              <select
                value={sourceType}
                aria-label="Starting point"
                onChange={(e) => setSourceType(e.target.value as SourceType)}
              >
                <option value="none">New project</option>
                <option value="zip">Existing repository (zip upload)</option>
                <option value="git">Existing repository (public https git URL)</option>
                <option value="task">Continue from an accepted task</option>
              </select>
            </label>
            {sourceType === "task" && (
              <ChainPicker
                value={fromTask}
                onChange={(id, t) => {
                  setFromTask(id);
                  setFromProject(t?.project_id ?? null);
                }}
              />
            )}
            {sourceType === "zip" && (
              <label
                className={`dropzone${dragging ? " over" : ""}${zip ? " has" : ""}`}
                onDragEnter={() => setDragging(true)}
                onDragLeave={() => setDragging(false)}
                onDrop={() => setDragging(false)}
              >
                <span className="dz-icon" aria-hidden="true">⇪</span>
                <span className="dz-text">{zip ? <>Ready: <b>{zip.name}</b></> : <>Drop a <b>.zip</b> here, or click to choose</>}</span>
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
            {(sourceType === "zip" || sourceType === "git") && (
              <p className="muted small shield-note">
                The repository is treated as untrusted: it is never executed outside the sandbox, only text source
                files are used, and files containing credentials are excluded and never sent to a model.
              </p>
            )}
          </Section>

          <Section n={3} title="Acceptance criteria" sub="What must be true for the Reviewer to accept. Optional — the Planner adds its own.">
            <label>
              Acceptance criteria <span className="muted small">(one per line, optional — the Planner adds its own)</span>
              <textarea value={criteria} onChange={(e) => setCriteria(e.target.value)} rows={4} placeholder={"Returns 404 for unknown codes\nAll endpoints have tests"} />
            </label>
            {criteriaList.length > 0 && (
              <ul className="crit-preview">
                {criteriaList.slice(0, 8).map((c, i) => (
                  <li key={i}><span aria-hidden="true">✓</span>{c}</li>
                ))}
              </ul>
            )}
          </Section>

          <Section n={4} title="Guardrails" sub="Hard limits the server enforces, plus how much control you keep.">
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
            <label className="check switch">
              <input type="checkbox" checked={planApproval} onChange={(e) => setPlanApproval(e.target.checked)} />
              Pause for my approval after planning, before any code is written
            </label>
            <label className="check switch">
              <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} />
              Let LoopForge reuse what it learns from this task's repairs as hints for other tasks in this organization
            </label>
            <p className="muted small">
              Budgets are enforced by the server: reaching one escalates the task instead of spending more. A repair
              that touches many files always waits for your approval.
            </p>
          </Section>
        </form>

        <aside className={`preview q-${quality.level}${busy ? " launching" : ""}`} aria-label="Loop preview">
          <div className="pv-head">
            <span className="pv-kicker">Loop preview</span>
            <strong className="pv-name">{name || "untitled"}</strong>
          </div>
          <ol className="pv-pipe" aria-hidden="true" style={{ "--charge": `${quality.score}%` } as React.CSSProperties}>
            {["Plan", "Build", "Verify", "Review", "Decide"].map((s) => <li key={s}><i />{s}</li>)}
          </ol>
          <dl className="pv-facts">
            <div><dt>Language</dt><dd>{langLabel}</dd></div>
            <div><dt>Start</dt><dd>{sourceLabel}</dd></div>
            <div><dt>Max rounds</dt><dd>{maxIterations}</dd></div>
            <div><dt>Criteria</dt><dd>{criteriaList.length || "planner's own"}</dd></div>
            <div><dt>Budget</dt><dd>{tokenBudget ? `${Number(tokenBudget).toLocaleString()} tok` : "default"}{maxCost ? ` · $${maxCost}` : ""}</dd></div>
            <div><dt>Approval gate</dt><dd className={planApproval ? "on" : ""}>{planApproval ? "on" : "off"}</dd></div>
          </dl>
          <ForecastBlock
            language={language}
            words={requirement.trim() ? requirement.trim().split(/\s+/).length : 0}
            tokenBudget={tokenBudget ? Number(tokenBudget) : null}
            maxCost={maxCost ? Number(maxCost) : null}
          />
          <SimilarTasks
            requirement={requirement}
            onReuse={(t) => {
              setRequirement(t.requirement);
              setCriteria(t.acceptance_criteria.join("\n"));
              setMaxIterations(t.max_iterations);
              setFlash((f) => f + 1);
            }}
          />
          {error && <p className="error" role="alert">{error}</p>}
          <button form="task-composer" className="primary launch" disabled={busy}>
            <span className="rocket" aria-hidden="true">🚀</span>
            {busy ? "Starting…" : "Create and start"}
          </button>
          <p className="muted small pv-foot">Runs in a sandbox. You can cancel any time.</p>
        </aside>
      </div>
    </>
  );
}
