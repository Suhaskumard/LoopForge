import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../auth";
import type { Task } from "../api/types";

interface Item {
  label: string;
  hint: string;
  to: string;
}

const SHORTCUTS: [string, string][] = [
  ["Ctrl K", "Quick search"],
  ["g  c", "Command Center"],
  ["g  n", "New task"],
  ["g  g", "Task Graph"],
  ["g  l", "Lessons"],
  ["g  a", "Loop Analytics"],
  ["g  s", "Settings"],
  ["?", "This sheet"],
  ["Esc", "Close"],
];

/** The keyboard-shortcut cheat sheet ("?"). */
export function ShortcutSheet({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div className="palette sheet" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" onMouseDown={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <strong>Keyboard shortcuts</strong>
          <button ref={ref} className="link" onClick={onClose}>Close</button>
        </header>
        <ul>
          {SHORTCUTS.map(([k, what]) => (
            <li key={k} className="sheet-row">
              <span>{what}</span>
              <span>{k.split("  ").map((part) => <kbd key={part}>{part}</kbd>)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** Ctrl/Cmd+K quick jump: pages and recent tasks. Tasks load lazily the first time it opens. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [tasks, setTasks] = useState<Task[]>([]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setSel(0);
    input.current?.focus();
    api
      .get<Task[]>("/tasks", { limit: 30, order: "desc" })
      .then((t) => Array.isArray(t) && setTasks(t))
      .catch(() => undefined);
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const pages: Item[] = [
      { label: "Command Center", hint: "Page", to: "/" },
      ...(can("developer") ? [{ label: "New task", hint: "Page", to: "/tasks/new" }] : []),
      { label: "Task Graph", hint: "Page", to: "/graph" },
      { label: "Lessons", hint: "Page", to: "/lessons" },
      ...(can("developer") ? [{ label: "Continue an accepted task", hint: "Task chain", to: "/tasks/new?from=" }] : []),
      { label: "Loop Analytics", hint: "Page", to: "/analytics" },
      ...(can("admin") ? [{ label: "Admin", hint: "Page", to: "/admin" }] : []),
      { label: "Settings", hint: "Page", to: "/settings" },
    ];
    const all = [
      ...pages,
      ...tasks.map((t) => ({ label: t.requirement.slice(0, 70), hint: t.status.toLowerCase(), to: `/tasks/${t.id}` })),
    ];
    const needle = q.trim().toLowerCase();
    return (needle ? all.filter((i) => i.label.toLowerCase().includes(needle)) : all).slice(0, 8);
  }, [q, tasks, can]);

  if (!open) return null;
  const go = (i?: Item) => {
    if (!i) return;
    navigate(i.to);
    onClose();
  };
  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Quick search" onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={input}
          value={q}
          placeholder="Jump to a page or task…"
          aria-label="Search pages and tasks"
          onChange={(e) => {
            setQ(e.target.value);
            setSel(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            else if (e.key === "ArrowDown") {
              e.preventDefault();
              setSel((s) => Math.min(s + 1, items.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setSel((s) => Math.max(s - 1, 0));
            } else if (e.key === "Enter") go(items[sel]);
          }}
        />
        <ul>
          {items.map((i, n) => (
            <li key={i.to + i.label}>
              <button className={n === sel ? "on" : ""} onMouseEnter={() => setSel(n)} onClick={() => go(i)}>
                <span>{i.label}</span>
                <small>{i.hint}</small>
              </button>
            </li>
          ))}
          {items.length === 0 && <li className="muted palette-none">No matches.</li>}
        </ul>
      </div>
    </div>
  );
}
