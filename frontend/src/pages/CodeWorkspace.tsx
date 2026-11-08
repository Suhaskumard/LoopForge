import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { api } from "../api/client";
import type { FileContent, Iteration, IterationDetail, IterationDiff, LogEntry } from "../api/types";
import { TaskTabs } from "../components/Layout";
import { buildTree, Card, CodeView, DiffView, Empty, ErrorBox, FileTree, Loading } from "../components/ui";
import { useAsync } from "../hooks";

type Pane = "code" | "diff" | "logs";

/** Screen 4 — Code Workspace: file tree, viewer, logs, and a diff between ANY two iterations. */
export function CodeWorkspace() {
  const { id = "" } = useParams();
  const its = useAsync(() => api.get<Iteration[]>(`/tasks/${id}/iterations`), [id]);
  const [chosen, setChosen] = useState<string>();
  const [against, setAgainst] = useState<string>(""); // "" = previous iteration
  const [selected, setSelected] = useState<string | null>(null);
  const [pane, setPane] = useState<Pane>("code");

  const iterations = its.data ?? [];
  const current = iterations.find((i) => i.id === chosen) ?? iterations[iterations.length - 1];

  const detail = useAsync(
    () => (current ? api.get<IterationDetail>(`/iterations/${current.id}`) : Promise.resolve(undefined)),
    [current?.id],
  );
  const diff = useAsync(
    () =>
      current
        ? api.get<IterationDiff>(`/iterations/${current.id}/diff`, { against: against || undefined })
        : Promise.resolve(undefined),
    [current?.id, against],
  );
  const file = useAsync(
    () =>
      current && selected
        ? api.get<FileContent>(`/iterations/${current.id}/files/${selected}`)
        : Promise.resolve(undefined),
    [current?.id, selected],
  );
  const logs = useAsync(
    () => (current ? api.get<LogEntry[]>(`/iterations/${current.id}/logs`) : Promise.resolve([])),
    [current?.id],
  );

  const files = useMemo(() => detail.data?.files ?? [], [detail.data]);
  const tree = useMemo(() => buildTree(files.map((f) => f.path)), [files]);
  const changed = useMemo(() => new Set(diff.data?.files.map((f) => f.path) ?? []), [diff.data]);
  const fileDiff = diff.data?.files.find((f) => f.path === selected);

  return (
    <>
      <header className="page-head"><h1>Code Workspace</h1></header>
      <TaskTabs id={id} />
      {its.error && <ErrorBox error={its.error} />}
      {its.loading && !its.data && <Loading />}
      {its.data && iterations.length === 0 && <Empty>No code has been generated for this task yet.</Empty>}

      {current && (
        <>
          <div className="row toolbar">
            <label>
              Version
              <select value={current.id} onChange={(e) => { setChosen(e.target.value); setSelected(null); }} data-testid="version">
                {iterations.map((i) => (
                  <option key={i.id} value={i.id}>v{i.number} — {i.status.replace(/_/g, " ")}</option>
                ))}
              </select>
            </label>
            <label>
              Compare with
              <select value={against} onChange={(e) => setAgainst(e.target.value)} data-testid="compare">
                <option value="">previous version</option>
                {iterations.filter((i) => i.id !== current.id).map((i) => (
                  <option key={i.id} value={i.id}>v{i.number}</option>
                ))}
              </select>
            </label>
            <div className="seg">
              {(["code", "diff", "logs"] as Pane[]).map((p) => (
                <button key={p} className={pane === p ? "on" : ""} onClick={() => setPane(p)}>{p}</button>
              ))}
            </div>
          </div>

          <div className="workspace">
            <Card title={`Files · v${current.number}`}>
              {files.length === 0 ? <Empty>No files.</Empty> : (
                <FileTree nodes={tree} selected={selected} onSelect={(p) => { setSelected(p); if (pane === "logs") setPane("code"); }} changed={changed} />
              )}
            </Card>

            <Card
              title={pane === "logs" ? "Execution logs" : (selected ?? "Select a file")}
              actions={diff.data && <span className="muted small">{diff.data.against ? `vs v${diff.data.against}` : "first version"} · {changed.size} changed</span>}
            >
              {pane === "code" && (
                <>
                  {file.error && <ErrorBox error={file.error} />}
                  {!selected && <Empty>Pick a file from the tree.</Empty>}
                  {file.data && <CodeView content={file.data.content} />}
                </>
              )}
              {pane === "diff" && (
                <>
                  {diff.error && <ErrorBox error={diff.error} />}
                  {!selected && (diff.data?.files.length ?? 0) > 0 && (
                    <ul className="changes">
                      {diff.data?.files.map((f) => (
                        <li key={f.path}><button className="link" onClick={() => setSelected(f.path)}>{f.path}</button> <span className="muted">{f.status}</span></li>
                      ))}
                    </ul>
                  )}
                  {!selected && diff.data?.files.length === 0 && <Empty>No differences.</Empty>}
                  {selected && (fileDiff ? <DiffView diff={fileDiff.diff} /> : <Empty>This file is identical in both versions.</Empty>)}
                </>
              )}
              {pane === "logs" && (
                <>
                  {logs.data?.length === 0 && <Empty>No execution logs for this version.</Empty>}
                  {logs.data?.map((l) => (
                    <details key={l.name} open>
                      <summary>{l.name}</summary>
                      <pre className="code terminal">{l.content}</pre>
                    </details>
                  ))}
                </>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
