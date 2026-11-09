import { useState } from "react";
import { api } from "../api/client";
import type { Explanation } from "../api/types";
import { useAsync } from "../hooks";
import { toast } from "./Toast";
import { Card } from "./ui";

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

/** "Why did this fail?": AI-written when a model answers, otherwise composed from the evidence. */
export function ExplainerCard({
  taskId,
  status,
  canAct,
  onRetried,
}: {
  taskId: string;
  status: string;
  canAct: boolean;
  onRetried?: () => void;
}) {
  const stored = useAsync(() => api.get<Explanation | null>(`/tasks/${taskId}/explanation`), [taskId]);
  const [fresh, setFresh] = useState<Explanation | null>(null);
  const [busy, setBusy] = useState<"explain" | "apply" | null>(null);
  const [showFacts, setShowFacts] = useState(false);
  if (status !== "FAILED" && status !== "ESCALATED") return null;
  const exp = fresh ?? stored.data ?? null;

  const explain = async () => {
    setBusy("explain");
    try {
      setFresh(await api.post<Explanation>(`/tasks/${taskId}/explanation`));
    } catch (e) {
      toast(message(e), "bad");
    } finally {
      setBusy(null);
    }
  };
  const apply = async () => {
    setBusy("apply");
    try {
      await api.post(`/tasks/${taskId}/explanation/apply`);
      toast("Retrying with the suggested fix — the Repair agent has it as a note", "ok");
      onRetried?.();
    } catch (e) {
      toast(message(e), "bad");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      title="Why did this fail?"
      actions={exp && (
        <span className="row">
          <span className={`badge ${exp.source === "ai" ? "info" : "muted"}`}>{exp.source === "ai" ? "AI analysis" : "From the evidence"}</span>
          <span className={`badge ${exp.confidence === "high" ? "ok" : exp.confidence === "medium" ? "warn" : "muted"}`}>{exp.confidence} confidence</span>
        </span>
      )}
    >
      <div className={`explainer${busy === "explain" ? " thinking" : ""}`} data-testid="explainer">
        {!exp ? (
          <div className="explainer-empty">
            <span className="explainer-orb" aria-hidden="true" />
            <p className="muted">Get a plain-English diagnosis: what went wrong across the iterations, the likely root cause, and what to change.</p>
            {canAct && (
              <button type="button" className="primary" disabled={busy !== null} onClick={() => void explain()}>
                {busy === "explain" ? "Analysing…" : "Explain this failure"}
              </button>
            )}
          </div>
        ) : (
          <>
            <p className="explainer-summary">{exp.summary}</p>
            <div className="explainer-grid">
              <section>
                <h3>Root causes</h3>
                <ol className="explainer-causes">{exp.root_causes.map((c, i) => <li key={i}>{c}</li>)}</ol>
              </section>
              <section className="explainer-fix">
                <h3>Suggested fix</h3>
                <p>{exp.suggested_fix}</p>
                <p className="muted small"><b>Note for the Repair agent:</b> {exp.retry_note}</p>
              </section>
            </div>
            <div className="row explainer-actions">
              {canAct && (
                <button type="button" className="primary" disabled={busy !== null} onClick={() => void apply()}>
                  {busy === "apply" ? "Starting…" : "Retry with this fix"}
                </button>
              )}
              {canAct && (
                <button type="button" disabled={busy !== null} onClick={() => void explain()}>
                  {busy === "explain" ? "Analysing…" : "Re-explain"}
                </button>
              )}
              <button type="button" className="link" aria-expanded={showFacts} onClick={() => setShowFacts(!showFacts)}>
                {showFacts ? "Hide" : "Show"} the {exp.evidence.length} facts it used
              </button>
            </div>
            {showFacts && <ul className="explainer-facts">{exp.evidence.map((f, i) => <li key={i}>{f}</li>)}</ul>}
          </>
        )}
      </div>
    </Card>
  );
}
