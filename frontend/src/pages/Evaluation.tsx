import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Iteration, IterationDetail, Requirement } from "../api/types";
import { TaskTabs } from "../components/Layout";
import { Card, Empty, ErrorBox, Kpi, Loading, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";
import { pct, score } from "../lib/format";

/** Screen 5 — Evaluation Center: tests, coverage, quality, security and acceptance status. */
export function Evaluation() {
  const { id = "" } = useParams();
  const its = useAsync(() => api.get<Iteration[]>(`/tasks/${id}/iterations`), [id]);
  const reqs = useAsync(() => api.get<Requirement[]>(`/tasks/${id}/requirements`), [id]);
  const [chosen, setChosen] = useState<string>();
  const iterations = its.data ?? [];
  const current = iterations.find((i) => i.id === chosen) ?? iterations[iterations.length - 1];
  const detail = useAsync(
    () => (current ? api.get<IterationDetail>(`/iterations/${current.id}`) : Promise.resolve(undefined)),
    [current?.id],
  );
  const d = detail.data;
  const tests = d?.test_results[d.test_results.length - 1];
  const q = d?.quality;
  const failures = tests?.details.failures ?? [];

  return (
    <>
      <header className="page-head"><h1>Evaluation Center</h1></header>
      <TaskTabs id={id} />
      {its.error && <ErrorBox error={its.error} />}
      {its.loading && !its.data && <Loading />}
      {its.data && iterations.length === 0 && <Empty>Nothing to evaluate yet.</Empty>}

      {current && (
        <>
          <div className="row toolbar">
            <label>
              Iteration
              <select value={current.id} onChange={(e) => setChosen(e.target.value)}>
                {iterations.map((i) => <option key={i.id} value={i.id}>v{i.number} — {i.status.replace(/_/g, " ")}</option>)}
              </select>
            </label>
            {d?.decision && <span className="muted">Decision Engine: <strong>{d.decision.action}</strong></span>}
          </div>

          <div className="kpis">
            <Kpi label="Tests passed" value={tests ? `${tests.passed} / ${tests.total_tests}` : "—"} hint={tests ? `${tests.failed} failed · ${tests.skipped} skipped` : ""} />
            <Kpi label="Coverage" value={pct(tests?.coverage ?? null)} />
            <Kpi label="Quality score" value={score(d?.quality_score)} hint="0–100, reviewer + tools" />
            <Kpi label="Lint findings" value={q ? String(q.ruff.length) : "—"} />
            <Kpi label="High security findings" value={q ? String(q.bandit_high.length) : "—"} hint={q ? `${q.bandit_other} lower severity` : ""} />
          </div>

          {failures.length > 0 && (
            <Card title="Failing tests">
              {failures.map((f) => (
                <details key={f.nodeid} open>
                  <summary><code>{f.nodeid}</code> — {f.message}</summary>
                  <pre className="code terminal">{f.traceback}</pre>
                </details>
              ))}
            </Card>
          )}

          <div className="grid2">
            <Card title="Acceptance criteria">
              {!d?.review ? <Empty>Not reviewed yet.</Empty> : (
                <ul className="checks" data-testid="criteria">
                  {d.review.acceptance_criteria.map((c) => (
                    <li key={c.criterion} className={c.met ? "met" : "unmet"}>
                      <span aria-hidden>{c.met ? "✔" : "✘"}</span> {c.criterion}
                      <div className="muted small">{c.evidence}</div>
                    </li>
                  ))}
                </ul>
              )}
              {d?.review && d.review.critical_issues.length > 0 && (
                <>
                  <h3>Critical issues</h3>
                  <ul>{d.review.critical_issues.map((i) => <li key={i}>{i}</li>)}</ul>
                </>
              )}
            </Card>

            <Card title="Code quality & security">
              {!q ? <Empty>No quality report yet.</Empty> : (
                <>
                  {q.tool_errors.length > 0 && <p className="error">{q.tool_errors.join("; ")}</p>}
                  {q.ruff.length === 0 && q.bandit_high.length === 0 && <p className="ok-text">No lint or high-severity security findings.</p>}
                  {q.ruff.length > 0 && (
                    <table className="table">
                      <thead><tr><th>Rule</th><th>Where</th><th>Message</th></tr></thead>
                      <tbody>
                        {q.ruff.map((r, i) => (
                          <tr key={i}><td><code>{r.code}</code></td><td>{r.file}:{r.line}</td><td>{r.message}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {q.bandit_high.map((b, i) => (
                    <p key={i} className="error">{b.test_id} {b.issue} ({b.file}:{b.line})</p>
                  ))}
                </>
              )}
            </Card>
          </div>

          <Card title="Requirement traceability">
            {reqs.data && reqs.data.length > 0 ? (
              <table className="table" data-testid="requirements">
                <thead><tr><th>ID</th><th>Requirement</th><th>Type</th><th>Implemented in</th><th>Verification</th></tr></thead>
                <tbody>
                  {reqs.data.map((r) => (
                    <tr key={r.req_id}>
                      <td><code>{r.req_id}</code></td>
                      <td>{r.description}</td>
                      <td>{r.req_type}</td>
                      <td className="muted small">{r.impl_mapping.join(", ") || "—"}</td>
                      <td><StatusBadge status={r.verification_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <Empty>No requirements recorded.</Empty>}
          </Card>
        </>
      )}
    </>
  );
}
