import { Link } from "react-router";
import { api } from "../api/client";
import type { OnboardingStep } from "../api/types";
import { useAsync } from "../hooks";

/** Getting-started checklist, derived server-side from what the user has actually done. */
export function Onboarding() {
  const o = useAsync(() => api.get<{ steps: OnboardingStep[]; complete: boolean }>("/me/onboarding"), []);
  if (!o.data || o.data.complete) return null;
  const done = o.data.steps.filter((s) => s.done).length;
  return (
    <section className="card" aria-labelledby="onb-h" data-testid="onboarding">
      <h2 id="onb-h">
        Getting started ({done}/{o.data.steps.length})
      </h2>
      <ul className="checks">
        {o.data.steps.map((s) => (
          <li key={s.id} className={s.done ? "met" : "unmet"}>
            <span aria-hidden="true">{s.done ? "✓" : "○"}</span> <strong>{s.title}</strong>
            <span className="visually-hidden">{s.done ? " (done)" : " (to do)"}</span>
            {!s.done && <span className="muted small"> — {s.hint}</span>}
          </li>
        ))}
      </ul>
      <Link className="button primary" to="/tasks/new">
        Start a task
      </Link>
    </section>
  );
}
