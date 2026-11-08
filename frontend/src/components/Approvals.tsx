import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Approval } from "../api/types";
import { useAsync } from "../hooks";

/**
 * Human approval gate (spec 13.2). Shows the pending request(s) for a task and lets the owner
 * approve (the run resumes) or reject (the task is escalated). `signal` changes whenever new
 * events arrive, which refreshes the list.
 */
export function Approvals({ taskId, signal, onDecided }: { taskId: string; signal: number; onDecided: () => void }) {
  const list = useAsync(() => api.get<Approval[]>(`/tasks/${taskId}/approvals`), [taskId, signal]);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const reload = list.reload;
  useEffect(() => {
    setError(undefined);
  }, [signal]);

  const pending = (list.data ?? []).filter((a) => a.status === "pending");
  if (pending.length === 0) return null;

  const decide = async (a: Approval, verb: "approve" | "reject") => {
    setBusy(a.id);
    setError(undefined);
    try {
      await api.post(`/tasks/${taskId}/approvals/${a.id}/${verb}`);
      reload();
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record the decision");
    } finally {
      setBusy(undefined);
    }
  };

  return (
    <section className="banner" role="alert" data-testid="approvals">
      <strong>The run is paused and needs your decision.</strong>
      {pending.map((a) => (
        <div key={a.id} className="approval">
          <div>
            <span className="badge warn">{a.kind === "plan" ? "plan review" : "large repair"}</span>{" "}
            iteration {a.iteration_number}: {a.summary}
            {a.detail.files && a.detail.files.length > 0 && (
              <ul className="small">
                {a.detail.files.map((f) => (
                  <li key={f}><code>{f}</code></li>
                ))}
              </ul>
            )}
          </div>
          <div className="row">
            <button className="primary" disabled={busy === a.id} onClick={() => void decide(a, "approve")}>Approve and continue</button>
            <button disabled={busy === a.id} onClick={() => void decide(a, "reject")}>Reject (escalate)</button>
          </div>
        </div>
      ))}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
