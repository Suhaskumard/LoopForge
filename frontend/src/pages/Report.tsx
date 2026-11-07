import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { FileEntry, Iteration, IterationDetail, Task, TaskAnalytics } from "../api/types";
import { TaskTabs } from "../components/Layout";
import { Card, Empty, ErrorBox, Kpi, Loading, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";
import { money, score, seconds } from "../lib/format";

/** Screen 7 — Final Report: outcome, iteration history, summaries and downloadable artifacts. */
export function Report() {
  const { id = "" } = useParams();
  const task = useAsync(() => api.get<Task>(`/tasks/${id}`), [id]);
  const its = useAsync(() => api.get<Iteration[]>(`/tasks/${id}/iterations`), [id]);
  const files = useAsync(() => api.get<FileEntry[]>(`/tasks/${id}/files`), [id]);
  const stats = useAsync(() => api.get<TaskAnalytics>(`/analytics/tasks/${id}`), [id]);
  const last = its.data?.[its.data.length - 1];
  const detail = useAsync(
    () => (last ? api.get<IterationDetail>(`/iterations/${last.id}`) : Promise.resolve(undefined)),
    [last?.id],
  );
  const [dlError, setDlError] = useState<string>();

  const download = async () => {
    setDlError(undefined);
    try {
      const blob = await api.blob(`/tasks/${id}/download`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `task-${id}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setDlError(e instanceof Error ? e.message : "Download failed");
    }
  };

  const t = task.data;
  const review = detail.data?.review;
  const tests = detail.data?.test_results[detail.data.test_results.length - 1];

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Final Report</h1>
          {t && <p className="muted clip">{t.requirement}</p>}
        </div>
        {t && <StatusBadge status={t.status} />}
      </header>
      <TaskTabs id={id} />
      {task.error && <ErrorBox error={task.error} />}
      {!t && task.loading && <Loading />}

      {t && (
        <div className="kpis">
          <Kpi label="Final status" value={t.status} />
          <Kpi label="Iterations" value={`${its.data?.length ?? 0} / ${t.max_iterations}`} />
          <Kpi label="Tests" value={tests ? `${tests.passed} / ${tests.total_tests} passed` : "—"} />
          <Kpi label="Quality" value={score(last?.quality_score)} />
          <Kpi label="Execution time" value={seconds(stats.data?.execution_seconds)} />
          <Kpi label="Estimated cost" value={money(stats.data?.estimated_cost)} hint="tokens × rate" />
        </div>
      )}

      <div className="grid2">
        <Card title="Iteration history">
          {its.data && its.data.length === 0 && <Empty>No iterations ran.</Empty>}
          <ol className="history" data-testid="history">
            {its.data?.map((i) => (
              <li key={i.id}>
                <div><strong>v{i.number}</strong> <StatusBadge status={i.status} /></div>
                <div className="muted small">
                  {i.tests.total_tests !== undefined ? `${i.tests.passed}/${i.tests.total_tests} tests passed` : "no tests recorded"}
                  {i.decision ? ` · decision: ${i.decision.action}` : ""}
                </div>
                {i.repair?.root_cause && <div className="small">Repair: {i.repair.root_cause}</div>}
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Review summary">
          {!review ? <Empty>No review recorded.</Empty> : (
            <>
              <p>
                {review.acceptance_criteria.filter((c) => c.met).length} of {review.acceptance_criteria.length} acceptance
                criteria met; {review.requirement_coverage.filter((r) => r.covered).length} of{" "}
                {review.requirement_coverage.length} requirements covered.
              </p>
              {review.critical_issues.length > 0 && <ul>{review.critical_issues.map((c) => <li key={c}>{c}</li>)}</ul>}
              {review.maintainability_notes.length > 0 && (
                <ul className="small">{review.maintainability_notes.map((n) => <li key={n}>{n}</li>)}</ul>
              )}
            </>
          )}
        </Card>
      </div>

      <Card title="Generated files" actions={<button className="primary" onClick={() => void download()} disabled={!files.data?.length}>Download .zip</button>}>
        {dlError && <p className="error" role="alert">{dlError}</p>}
        {files.data && files.data.length === 0 && <Empty>No files were generated.</Empty>}
        <table className="table">
          <tbody>
            {files.data?.map((f) => (
              <tr key={f.path}><td><code>{f.path}</code></td><td className="muted small">sha256 {f.sha256.slice(0, 12)}…</td></tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
