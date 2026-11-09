import { Fragment, useMemo, useRef, useState, type ReactNode } from "react";
import { dominantKind, langOf, tokenizeLine } from "../lib/highlight";
import { parseUnifiedDiff, diffStats } from "../lib/diff";

const STATUS_CLASS: Record<string, string> = {
  COMPLETED: "ok",
  accepted: "ok",
  passed: "ok",
  success: "ok",
  FAILED: "bad",
  failed: "bad",
  failed_tests: "bad",
  rejected: "bad",
  ESCALATED: "warn",
  escalated: "warn",
  CANCELLED: "muted",
  cancelled: "muted",
  PENDING: "muted",
};

export function StatusBadge({ status }: { status: string }) {
  const live = status === "RUNNING" || status === "running";
  return <span className={`badge ${STATUS_CLASS[status] ?? "info"}${live ? " live-run" : ""}`}>{status.replace(/_/g, " ")}</span>;
}

/** Page title with an icon badge and optional subtitle/actions. The h1 text is exactly `title`. */
export function PageHeader({ icon, title, sub, children }: { icon: ReactNode; title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head ph">
      <div className="ph-main">
        <span className="ph-icon" aria-hidden="true">{icon}</span>
        <div className="ph-text">
          <h1>{title}</h1>
          {sub && <div className="muted ph-sub">{sub}</div>}
        </div>
      </div>
      {children && <div className="row ph-actions">{children}</div>}
    </header>
  );
}

/** Animated ring for a 0–100 score. Decorative: the number is also shown as text. */
export function ScoreRing({ value, label }: { value: number | null | undefined; label: string }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const tone = v >= 80 ? "ok" : v >= 50 ? "warn" : "bad";
  return (
    <figure className={`ring ${value == null ? "none" : tone}`}>
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <defs>
          <linearGradient id="ring-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--primary)" />
            <stop offset="1" stopColor="var(--primary-2)" />
          </linearGradient>
        </defs>
        <circle className="ring-track" cx="50" cy="50" r={r} />
        <circle
          className="ring-bar"
          cx="50"
          cy="50"
          r={r}
          strokeDasharray={c}
          style={{ "--off": `${c * (1 - v / 100)}`, "--full": `${c}` } as React.CSSProperties}
        />
      </svg>
      <figcaption>
        <strong>{value == null ? "—" : Math.round(v)}</strong>
        <span>{label}</span>
      </figcaption>
    </figure>
  );
}

export function Kpi({ label, value, hint, className = "" }: { label: string; value: string; hint?: ReactNode; className?: string }) {
  return (
    <div className={`kpi ${className}`} data-testid={`kpi-${label}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          <h2>{title}</h2>
          <div>{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div className="loading" role="status">
      <p className="muted">{what}…</p>
      <span className="skeleton" aria-hidden="true" />
      <span className="skeleton" aria-hidden="true" style={{ width: "70%" }} />
      <span className="skeleton" aria-hidden="true" style={{ width: "45%" }} />
    </div>
  );
}

export function ErrorBox({ error }: { error: Error }) {
  return <p className="error" role="alert">{error.message}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted empty">{children}</p>;
}

/** Renders a unified diff as text. Generated code is untrusted: it is never interpreted as HTML. */
export function DiffView({ diff }: { diff: string }) {
  const lines = parseUnifiedDiff(diff);
  const { added, removed } = diffStats(lines);
  return (
    <div className="diff" data-testid="diff">
      <div className="diff-stats">
        <span className="add">+{added}</span> <span className="del">−{removed}</span>
      </div>
      <pre>
        {lines.map((l, i) => (
          <div key={i} className={`dl ${l.kind}`}>
            <span className="no">{l.oldNo ?? ""}</span>
            <span className="no">{l.newNo ?? ""}</span>
            <span className="sign">{l.kind === "add" ? "+" : l.kind === "del" ? "−" : " "}</span>
            <span className="txt">{l.text}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

/** Syntax-colored, line-numbered code with a clickable minimap. Tokens are rendered as text, never HTML. */
export interface LineNote {
  id: string;
  line: number | null;
  body: string;
  author: string;
  resolved: boolean;
}

export function CodeView({
  content,
  path,
  notes,
  onNote,
}: {
  content: string;
  path?: string | null;
  notes?: LineNote[]; // comments on this file
  onNote?: (line: number, body: string) => Promise<void>; // present = people may comment
}) {
  const lang = langOf(path);
  const lines = useMemo(() => content.split("\n").map((l) => tokenizeLine(l, lang)), [content, lang]);
  const pre = useRef<HTMLPreElement>(null);
  const [composing, setComposing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const byLine = useMemo(() => {
    const m = new Map<number, LineNote[]>();
    for (const n of notes ?? []) if (n.line) m.set(n.line, [...(m.get(n.line) ?? []), n]);
    return m;
  }, [notes]);
  const jump = (i: number) => {
    const el = pre.current?.querySelector<HTMLElement>(`[data-ln="${i + 1}"]`);
    if (pre.current && el) pre.current.scrollTo({ top: el.offsetTop - 40, behavior: "smooth" });
  };
  const save = async (line: number) => {
    if (!onNote || !draft.trim()) return;
    await onNote(line, draft.trim());
    setDraft("");
    setComposing(null);
  };
  return (
    <div className="editor">
      <pre className={`code lang-${lang}`} data-testid="code" ref={pre}>
        {lines.map((tokens, i) => {
          const n = i + 1;
          const here = byLine.get(n);
          return (
            <Fragment key={i}>
              <div className={`dl ctx${here ? " has-note" : ""}`} data-ln={n}>
                {onNote ? (
                  <button type="button" className="no no-btn" title="Leave a note on this line for the Repair agent" aria-label={`Comment on line ${n}`} onClick={() => setComposing(composing === n ? null : n)}>
                    {n}
                  </button>
                ) : (
                  <span className="no">{n}</span>
                )}
                <span className="txt">
                  {tokens.map((t, j) => (t.kind === "txt" ? t.text : <span key={j} className={`tk-${t.kind}`}>{t.text}</span>))}
                </span>
              </div>
              {(here || composing === n) && (
                <div className="note-thread">
                  {here?.map((c) => (
                    <div key={c.id} className={`note${c.resolved ? " resolved" : ""}`}>
                      <b>{c.author || "someone"}</b>
                      <span>{c.body}</span>
                      {c.resolved && <small className="muted">resolved</small>}
                    </div>
                  ))}
                  {composing === n && (
                    <form className="note-form" onSubmit={(e) => { e.preventDefault(); void save(n); }}>
                      <textarea
                        autoFocus
                        rows={2}
                        value={draft}
                        maxLength={2000}
                        aria-label={`Note for line ${n}`}
                        placeholder="e.g. this should return 404 when the id does not exist"
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void save(n); }
                          if (e.key === "Escape") setComposing(null);
                        }}
                      />
                      <div className="row">
                        <button className="primary" disabled={!draft.trim()}>Add note</button>
                        <button type="button" onClick={() => setComposing(null)}>Cancel</button>
                        <small className="muted">The Repair agent reads unresolved notes on its next repair.</small>
                      </div>
                    </form>
                  )}
                </div>
              )}
            </Fragment>
          );
        })}
      </pre>
      {lines.length > 12 && (
        <div className="minimap" aria-hidden="true">
          {lines.map((tokens, i) => {
            const len = tokens.reduce((n, t) => n + t.text.length, 0);
            const indent = (tokens[0]?.text.match(/^\s*/)?.[0].length ?? 0);
            return (
              <i
                key={i}
                className={`mm-${dominantKind(tokens)}`}
                style={{ marginLeft: `${Math.min(indent, 40) * 1.2}%`, width: `${Math.min(100, Math.max(len ? 4 : 0, (len - indent) * 1.3))}%` }}
                onClick={() => jump(i)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

const EXT_TONE: Record<string, string> = { py: "py", js: "js", jsx: "js", ts: "ts", tsx: "ts", json: "json", md: "md", txt: "txt", toml: "cfg", yml: "cfg", yaml: "cfg", cfg: "cfg", ini: "cfg" };
const extTone = (name: string) => EXT_TONE[name.split(".").pop()?.toLowerCase() ?? ""] ?? "other";

export interface TreeNode {
  name: string;
  path: string;
  children: TreeNode[];
  file: boolean;
}

export function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", children: [], file: false };
  for (const p of [...paths].sort()) {
    let node = root;
    const parts = p.split("/");
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      let child = node.children.find((c) => c.name === part);
      if (!child) {
        child = { name: part, path, children: [], file: i === parts.length - 1 };
        node.children.push(child);
      }
      node = child;
    });
  }
  const order = (n: TreeNode) => {
    n.children.sort((a, b) => Number(a.file) - Number(b.file) || a.name.localeCompare(b.name));
    n.children.forEach(order);
  };
  order(root);
  return root.children;
}

export function FileTree({
  nodes,
  selected,
  onSelect,
  changed,
}: {
  nodes: TreeNode[];
  selected: string | null;
  onSelect: (path: string) => void;
  changed?: Set<string>;
}) {
  return (
    <ul className="tree">
      {nodes.map((n) => (
        <li key={n.path}>
          {n.file ? (
            <button
              className={`file ${selected === n.path ? "sel" : ""}`}
              onClick={() => onSelect(n.path)}
              data-testid={`file-${n.path}`}
            >
              <span className={`ft ft-${extTone(n.name)}`} aria-hidden="true" />
              {n.name}
              {changed?.has(n.path) && <span className="dot" title="changed" />}
            </button>
          ) : (
            <>
              <span className="dir"><span className="chev" aria-hidden="true">▾</span>{n.name}/</span>
              <FileTree nodes={n.children} selected={selected} onSelect={onSelect} changed={changed} />
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
