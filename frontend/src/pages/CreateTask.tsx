import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Project, Task } from "../api/types";
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
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const project = await api.post<Project>("/projects", { name });
      const task = await api.post<Task>("/tasks", {
        project_id: project.id,
        requirement,
        max_iterations: maxIterations,
        acceptance_criteria: criteria.split("\n").map((c) => c.trim()).filter(Boolean),
      });
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
              Framework
              <select disabled value="FastAPI" aria-label="Framework">
                <option>FastAPI</option>
              </select>
            </label>
            <label>
              Iteration limit
              <input type="number" min={1} max={20} value={maxIterations} onChange={(e) => setMaxIterations(Number(e.target.value))} />
            </label>
          </div>
          <label>
            Acceptance criteria <span className="muted small">(one per line, optional — the Planner adds its own)</span>
            <textarea value={criteria} onChange={(e) => setCriteria(e.target.value)} rows={4} />
          </label>
          <p className="muted small">
            The model-token budget is enforced by the server for every run; hitting it escalates the task instead of
            spending more.
          </p>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary" disabled={busy}>{busy ? "Starting…" : "Create and start"}</button>
        </form>
      </Card>
    </>
  );
}
