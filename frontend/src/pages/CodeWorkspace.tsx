import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { api } from "../api/client";
import type { CodeComment, FileContent, Iteration, IterationDetail, IterationDiff, LogEntry } from "../api/types";
import { useAuth } from "../auth";
import { TaskTabs } from "../components/Layout";
import { IconCode } from "../components/icons";
import { buildTree, Card, CodeView, DiffView, Empty, ErrorBox, FileTree, Loading, PageHeader } from "../components/ui";
import { useAsync } from "../hooks";
import { toast } from "../components/Toast";
import { LANG_LABEL, langOf } from "../lib/highlight";

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
  const [openTabs, setOpenTabs] = useState<string[]>([]);
  const open = (p: string) => {
    setSelected(p);
    setOpenTabs((t) => (t.includes(p) ? t : [...t, p].slice(-8)));
  };
  const close = (p: string) => {
    const next = openTabs.filter((x) => x !== p);
    setOpenTabs(next);
    if (selected === p) setSelected(next[next.length - 1] ?? null);
  };
  const copy = async () => {
    if (!file.data) return;
    try {
      await navigator.clipboard.writeText(file.data.content);
      toast("Copied to clipboard", "ok");
    } catch {
      toast("Copy is blocked by the browser", "bad");
    }
  };
  const lineCount = file.data ? file.data.content.split("\n").length : 0;

  // Round 9: line notes that the Repair agent reads on its next repair
  const { can } = useAuth();
  const comments = useAsync(() => api.get<CodeComment[]>(`/tasks/${id}/comments`), [id]);
  const allNotes = useMemo(() => (Array.isArray(comments.data) ? comments.data : []), [comments.data]);
  const fileNotes = allNotes.filter((c) => c.file_path === selected);
  const openNotes = allNotes.filter((c) => !c.resolved);
  const addNote = async (line: number, body: string) => {
    try {
      await api.post(`/tasks/${id}/comments`, { file_path: selected ?? "", line, body, iteration_number: current?.number });
      toast("Note saved — the Repair agent will see it", "ok");
      comments.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save the note", "bad");
    }
  };
  const resolveNote = async (c: CodeComment) => {
    try {
      await api.request("PATCH", `/tasks/${id}/comments/${c.id}`, { json: { resolved: !c.resolved } });
      comments.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update the note", "bad");
    }
  };

  return (
    <>
      <PageHeader icon={<IconCode />} title="Code Workspace" sub="Every version the loop wrote — browse, diff and read the logs." />
      <TaskTabs id={id} />
      {its.error && <ErrorBox error={its.error} />}
      {its.loading && !its.data && <Loading />}
      {its.data && iterations.length === 0 && <Empty>No code has been generated for this task yet.</Empty>}

      {current && (
        <>
          <div className="row toolbar">
            <label>
              Version
              <select value={current.id} onChange={(e) => { setChosen(e.target.value); setSelected(null); setOpenTabs([]); }} data-testid="version">
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
                <FileTree nodes={tree} selected={selected} onSelect={(p) => { open(p); if (pane === "logs") setPane("code"); }} changed={changed} />
              )}
            </Card>

            <Card
              title={pane === "logs" ? "Execution logs" : (selected ?? "Select a file")}
              actions={diff.data && <span className="muted small">{diff.data.against ? `vs v${diff.data.against}` : "first version"} · {changed.size} changed</span>}
            >
              {pane !== "logs" && openTabs.length > 0 && (
                <div className="editor-tabs" role="tablist" aria-label="Open files">
                  {openTabs.map((p) => (
                    <div key={p} className={`etab${p === selected ? " on" : ""}`}>
                      <button role="tab" aria-selected={p === selected} className="etab-name" onClick={() => setSelected(p)} title={p}>
                        {p.split("/").pop()}
                        {changed.has(p) && <span className="dot" aria-label="changed" />}
                      </button>
                      <button className="etab-x" aria-label={`Close ${p}`} onClick={() => close(p)}>×</button>
                    </div>
                  ))}
                </div>
              )}
              {pane !== "logs" && selected && (
                <nav className="crumbs" aria-label="File path">
                  {selected.split("/").map((part, i, all) => (
                    <span key={i} className={i === all.length - 1 ? "last" : ""}>{part}</span>
                  ))}
                </nav>
              )}
              {pane === "code" && (
                <>
                  {file.error && <ErrorBox error={file.error} />}
                  {!selected && <Empty><span className="empty-art" aria-hidden="true">{"</>"}</span>Pick a file from the tree.</Empty>}
                  {file.data && (
                    <CodeView
                      content={file.data.content}
                      path={selected}
                      notes={fileNotes}
                      onNote={can("developer") ? addNote : undefined}
                    />
                  )}
                  {file.data && selected && (
                    <footer className="statusbar">
                      <span><i className={`ft ft-${langOf(selected) === "python" ? "py" : langOf(selected) === "js" ? "js" : "other"}`} />{LANG_LABEL[langOf(selected)]}</span>
                      <span>{lineCount} lines</span>
                      <span>v{current.number}</span>
                      {changed.has(selected) && <span className="changed">● changed in this version</span>}
                      <button className="statusbar-copy" onClick={() => void copy()}>Copy</button>
                    </footer>
                  )}
                </>
              )}
              {pane === "diff" && (
                <>
                  {diff.error && <ErrorBox error={diff.error} />}
                  {!selected && (diff.data?.files.length ?? 0) > 0 && (
                    <ul className="changes">
                      {diff.data?.files.map((f) => (
                        <li key={f.path}><button className="link" onClick={() => open(f.path)}>{f.path}</button> <span className="muted">{f.status}</span></li>
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
                      <pre className="code terminal"><span className="prompt" aria-hidden="true">$ </span>{l.content}</pre>
                    </details>
                  ))}
                </>
              )}
            </Card>
          </div>

          <Card
            title="Notes for the Repair agent"
            actions={<span className={`badge ${openNotes.length ? "warn" : "muted"}`}>{openNotes.length} open</span>}
          >
            {allNotes.length === 0 ? (
              <p className="muted small notes-help">
                {can("developer") ? "Click any line number in the editor to leave a note. " : ""}
                Unresolved notes are handed to the Repair agent on its next repair, as hints it weighs against the failing tests.
              </p>
            ) : (
              <ul className="notes-list">
                {allNotes.map((c) => (
                  <li key={c.id} className={c.resolved ? "resolved" : ""}>
                    <button type="button" className="link notes-where" onClick={() => { if (c.file_path) { open(c.file_path); setPane("code"); } }}>
                      <code>{c.file_path || "general"}{c.line ? `:${c.line}` : ""}</code>
                    </button>
                    <span className="notes-body">{c.body}</span>
                    <span className="muted small">{c.author}</span>
                    {can("developer") && (
                      <button type="button" className="notes-resolve" onClick={() => void resolveNote(c)}>
                        {c.resolved ? "Reopen" : "Resolve"}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </>
  );
}
