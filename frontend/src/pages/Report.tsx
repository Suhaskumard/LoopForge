import { useState } from "react";
import { useParams } from "react-router";
import { api } from "../api/client";
import type { FinalReport } from "../api/types";
import { TaskTabs } from "../components/Layout";
import { Card, Empty, ErrorBox, Kpi, Loading, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";
import { money, pct, score } from "../lib/format";

async function save(blob: Blob, name: string): Promise<void> {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** Screen 7 — Final Report. Everything shown comes from stored execution records (GET /report). */
export function Report() {
  const { id = "" } = useParams();
  const report = useAsync(() => api.get<FinalReport>(`/tasks/${id}/report`), [id]);
  const [dlError, setDlError] = useState<string>();
  const r = report.data;

  const download = async (path: string, name: string) => {
    setDlError(undefined);
    try {
      await save(await api.blob(path), name);
    } catch (e) {
      setDlError(e instanceof Error ? e.message : "Download failed");
    }
  };

  const unmet = r?.acceptance_criteria.filter((c) => !c.met).length ?? 0;
  return (
    <>
      <header className="page-head">
        <div>
          <h1>Final Report</h1>
          {r && <p className="muted clip">{r.requirement}</p>}
        </div>
        {r && <StatusBadge status={r.status} />}
      </header>
      <TaskTabs id={id} />
      {report.error && <ErrorBox error={report.error} />}
      {!r && report.loading && <Loading />}

      {r && (
        <>
          <section className={`banner ${r.status === "COMPLETED" ? "ok" : ""}`} data-testid="outcome">
            <strong>{r.outcome}</strong>
            {r.escalation_reason && <span>Reason: {r.escalation_reason}</span>}
          </section>

          {r.failure_explanation && (
            <Card title="Why it was not accepted">
              <div data-testid="failure-explanation">
                <ul>
                  {r.failure_explanation.what_failed.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
                <h3>What the Repair agent tried</h3>
                {r.failure_explanation.repair_attempts.length === 0 ? (
                  <p className="muted">No repair was attempted.</p>
                ) : (
                  <ul>
                    {r.failure_explanation.repair_attempts.map((a, i) => (
                      <li key={i}>
                        {a.failure_class || "failure"}: {a.root_cause} → {a.outcome}
                        {a.files.length > 0 && <span className="muted small"> ({a.files.join(", ")})</span>}
                      </li>
                    ))}
                  </ul>
                )}
                <h3>What a person should do</h3>
                <ol>
                  {r.failure_explanation.next_steps.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ol>
              </div>
            </Card>
          )}

          <div className="kpis">
            <Kpi label="Tests passed" value={`${r.tests.passed} / ${r.tests.total}`} hint={`coverage ${pct(r.tests.coverage, 0)}`} />
            <Kpi label="Iterations" value={String(r.iterations.length)} />
            <Kpi label="Quality" value={score(r.quality.score)} hint={`${r.quality.lint_findings} lint · ${r.quality.high_security_findings} high security`} />
            <Kpi label="Tokens" value={r.total_tokens.toLocaleString()} />
            <Kpi label="Estimated cost" value={money(r.estimated_cost)} hint="tokens × rate" />
          </div>

          <div className="grid2">
            <Card title="Iteration history">
              {r.iterations.length === 0 && <Empty>No iterations ran.</Empty>}
              <ol className="history" data-testid="history">
                {r.iterations.map((i) => (
                  <li key={i.number}>
                    <div><strong>v{i.number}</strong> <StatusBadge status={i.status} /></div>
                    <div className="muted small">
                      {i.tests_passed}/{i.tests_total} tests passed{i.decision ? ` · decision: ${i.decision}` : ""}
                    </div>
                    {i.repair_root_cause && (
                      <div className="small">Repair: {i.repair_root_cause} ({i.repair_files.join(", ")})</div>
                    )}
                  </li>
                ))}
              </ol>
            </Card>

            <Card title={`Acceptance criteria${r.acceptance_criteria.length ? ` · ${r.acceptance_criteria.length - unmet}/${r.acceptance_criteria.length} met` : ""}`}>
              {r.acceptance_criteria.length === 0 ? <Empty>No review was recorded.</Empty> : (
                <ul className="checks">
                  {r.acceptance_criteria.map((c) => (
                    <li key={c.criterion} className={c.met ? "met" : "unmet"}>
                      <span aria-hidden>{c.met ? "✔" : "✘"}</span> {c.criterion}
                      <div className="muted small">{c.evidence}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card title="Requirement traceability">
            {r.requirements.length === 0 ? <Empty>No requirements recorded.</Empty> : (
              <table className="table" data-testid="trace">
                <thead><tr><th>ID</th><th>Requirement</th><th>Implemented in</th><th>Tested in</th><th>Status</th></tr></thead>
                <tbody>
                  {r.requirements.map((q) => (
                    <tr key={q.req_id}>
                      <td><code>{q.req_id}</code></td>
                      <td>{q.description}</td>
                      <td className="small">{q.implemented_in.join(", ") || "—"}</td>
                      <td className="small">{q.tested_in.join(", ") || "—"}</td>
                      <td><StatusBadge status={q.verification_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {r.approvals.length > 0 && (
            <Card title="Human approvals">
              <ul>{r.approvals.map((a, i) => <li key={i}>{a.kind} (iteration {a.iteration}): <StatusBadge status={a.status} /></li>)}</ul>
            </Card>
          )}

          <Card
            title="Artifacts"
            actions={
              <div className="row">
                <button onClick={() => void download(`/tasks/${id}/report.md`, `report-${id}.md`)}>Report (.md)</button>
                <button className="primary" disabled={r.files.length === 0} onClick={() => void download(`/tasks/${id}/download`, `task-${id}.zip`)}>
                  Code (.zip)
                </button>
              </div>
            }
          >
            {dlError && <p className="error" role="alert">{dlError}</p>}
            {r.files.length === 0 && <Empty>No files were generated.</Empty>}
            <table className="table">
              <tbody>
                {r.files.map((f) => (
                  <tr key={f.path}><td><code>{f.path}</code></td><td className="muted small">sha256 {f.sha256.slice(0, 12)}…</td></tr>
                ))}
              </tbody>
            </table>
            {r.readme_generated && <p className="muted small">A README for the generated project is included in the .md report.</p>}
          </Card>
        </>
      )}
    </>
  );
}
