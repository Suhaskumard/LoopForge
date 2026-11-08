import { useEffect, useState, type FormEvent } from "react";
import { Link, useInRouterContext } from "react-router";
import { api } from "../api/client";
import type { Approval, ApprovalComment } from "../api/types";
import { useAsync } from "../hooks";

/** Inline review comments on an approval (Phase 15). The diff itself is on the Code Workspace tab. */
export function ReviewComments({
  taskId,
  approvalId,
  canComment,
}: {
  taskId: string;
  approvalId: string;
  canComment: boolean;
}) {
  const inRouter = useInRouterContext();
  const url = `/tasks/${taskId}/approvals/${approvalId}/comments`;
  const list = useAsync(() => api.get<ApprovalComment[]>(url), [url]);
  const [file, setFile] = useState("");
  const [line, setLine] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string>();
  const comments = Array.isArray(list.data) ? list.data.filter((c) => typeof c.body === "string") : [];

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      await api.post(url, { file_path: file.trim(), line: line ? Number(line) : null, body });
      setBody("");
      list.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the comment");
    }
  };

  return (
    <div className="review" data-testid="review-comments">
      {inRouter && (
        <Link to={`/tasks/${taskId}/code`} className="small">
          Review the code changes
        </Link>
      )}
      {comments.length > 0 && (
        <ul className="notes">
          {comments.map((c) => (
            <li key={c.id}>
              <strong>{c.author}</strong>
              {c.file_path && <code> {c.file_path}{c.line ? `:${c.line}` : ""}</code>}: {c.body}
            </li>
          ))}
        </ul>
      )}
      {canComment && (
        <form className="row" onSubmit={(e) => void add(e)}>
          <label>
            File
            <input value={file} onChange={(e) => setFile(e.target.value)} placeholder="app/main.py" />
          </label>
          <label>
            Line
            <input type="number" min={1} value={line} onChange={(e) => setLine(e.target.value)} />
          </label>
          <label>
            Comment
            <input value={body} onChange={(e) => setBody(e.target.value)} required maxLength={2000} />
          </label>
          <button>Add comment</button>
        </form>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}

/**
 * Human approval gate (spec 13.2). Shows the pending request(s) for a task and lets the owner
 * approve (the run resumes) or reject (the task is escalated). `signal` changes whenever new
 * events arrive, which refreshes the list.
 */
export function Approvals({
  taskId,
  signal,
  onDecided,
  canDecide = true,
}: {
  taskId: string;
  signal: number;
  onDecided: () => void;
  /** Only approvers and admins may decide; everyone else sees that the run is waiting. */
  canDecide?: boolean;
}) {
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
      <strong>{canDecide ? "The run is paused and needs your decision." : "The run is paused and waiting for an approver."}</strong>
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
          <ReviewComments taskId={taskId} approvalId={a.id} canComment={canDecide} />
          {canDecide ? (
            <div className="row">
              <button className="primary" disabled={busy === a.id} onClick={() => void decide(a, "approve")}>Approve and continue</button>
              <button disabled={busy === a.id} onClick={() => void decide(a, "reject")}>Reject (escalate)</button>
            </div>
          ) : (
            <p className="muted small">Your role cannot approve; ask an approver or admin of this organization.</p>
          )}
        </div>
      ))}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
