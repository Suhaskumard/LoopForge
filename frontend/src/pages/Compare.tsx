import { useEffect } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { Experiment } from "../api/types";
import { isTerminal } from "../api/types";
import { IconChart } from "../components/icons";
import { METRICS, verdict, type Metric } from "../components/Intel";
import { Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

const fmt: Record<Metric, (v: number) => string> = {
  quality: (v) => String(Math.round(v)),
  iterations: (v) => String(v),
  tokens: (v) => v.toLocaleString(),
  cost: (v) => (v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`),
  seconds: (v) => (v < 90 ? `${Math.round(v)}s` : `${Math.round(v / 60)} min`),
};

/** A/B results: two runs of the same task that differ only in one agent's model. */
export function Compare() {
  const [params] = useSearchParams();
  const id = params.get("experiment") ?? "";
  const exp = useAsync(
    () => (id ? api.get<Experiment>(`/experiments/${id}`) : Promise.resolve(undefined)),
    [id],
  );
  const variants = exp.data?.variants ?? [];
  const running = variants.some((v) => !isTerminal(v.status));
  const reload = exp.reload;
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => reload(), 4000); // live until both runs finish
    return () => window.clearInterval(t);
  }, [running, reload]);
  const v = verdict(variants);
  const agent = Object.keys(variants[0]?.model_overrides ?? {})[0] ?? "agent";

  return (
    <>
      <PageHeader
        icon={<IconChart />}
        title="A/B comparison"
        sub={variants.length ? <>Same task, same starting code — only the <b>{agent}</b> model differs.</> : "Compare two runs of the same task."}
      />
      {!id && <Empty>Start an A/B test from a task&apos;s Final Report.</Empty>}
      {exp.error && <ErrorBox error={exp.error} />}
      {exp.loading && !exp.data && <Loading what="Loading the experiment" />}

      {variants.length === 2 && (
        <>
          <div className={`ab-verdict${running ? " pending" : ""}`} role="status">
            {running ? (
              <><span className="orbit ab-orbit" aria-hidden="true"><span /><span /><span /></span> Both runs are in progress — results update live.</>
            ) : v.overall === null ? (
              <>It&apos;s a tie: neither model was clearly better.</>
            ) : (
              <>
                <span className="crown" aria-hidden="true">♛</span>
                <b>{Object.values(variants[v.overall].model_overrides)[0]}</b> wins
                {variants.filter((x) => x.status === "COMPLETED").length === 1 ? " — it was the only run accepted." : ` on ${Object.values(v.metric).filter((x) => x === v.overall).length} of ${METRICS.length} measures.`}
              </>
            )}
          </div>

          <div className="ab-cols">
            {variants.map((x, i) => (
              <section key={x.task_id} className={`ab-col${v.overall === i && !running ? " winner" : ""}`}>
                <header>
                  <span className="ab-tag">{i === 0 ? "A" : "B"}</span>
                  <code className="ab-model">{Object.values(x.model_overrides)[0]}</code>
                  <StatusBadge status={x.status} />
                </header>
                <ul className="ab-metrics">
                  {METRICS.map((m) => {
                    const val = x[m.id];
                    const other = variants[1 - i][m.id];
                    const max = Math.max(Number(val ?? 0), Number(other ?? 0)) || 1;
                    const won = v.metric[m.id] === i;
                    return (
                      <li key={m.id} className={won ? "won" : ""}>
                        <span className="abm-label">{m.label}{won && <span className="crown" aria-label="better"> ♛</span>}</span>
                        <span className="abm-bar" aria-hidden="true"><i style={{ width: `${(Number(val ?? 0) / max) * 100}%` }} /></span>
                        <span className="abm-val">{val === null || val === undefined ? "—" : fmt[m.id](Number(val))}</span>
                      </li>
                    );
                  })}
                </ul>
                <Link className="button" to={`/tasks/${x.task_id}`}>Open run {i === 0 ? "A" : "B"}</Link>
              </section>
            ))}
          </div>
          {variants[0].rerun_of && (
            <p className="muted small">
              Both runs repeat <Link to={`/tasks/${variants[0].rerun_of}/report`}>the original task</Link>. Lower is better for rounds, tokens, cost and time; higher for quality.
            </p>
          )}
        </>
      )}
    </>
  );
}
