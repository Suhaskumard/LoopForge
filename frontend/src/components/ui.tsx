import type { ReactNode } from "react";
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
  return <span className={`badge ${STATUS_CLASS[status] ?? "info"}`}>{status.replace(/_/g, " ")}</span>;
}

export function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="kpi" data-testid={`kpi-${label}`}>
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
  return <p className="muted" role="status">{what}…</p>;
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

export function CodeView({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <pre className="code" data-testid="code">
      {lines.map((l, i) => (
        <div key={i} className="dl ctx">
          <span className="no">{i + 1}</span>
          <span className="txt">{l}</span>
        </div>
      ))}
    </pre>
  );
}

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
              {n.name}
              {changed?.has(n.path) && <span className="dot" title="changed" />}
            </button>
          ) : (
            <>
              <span className="dir">{n.name}/</span>
              <FileTree nodes={n.children} selected={selected} onSelect={onSelect} changed={changed} />
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
