import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../auth";
import type { Task } from "../api/types";
import { rank } from "../lib/fuzzy";
import { actionsFor } from "./TaskExplorer";
import { toast } from "./Toast";

const SHORTCUTS: [string, string][] = [
  ["Ctrl K", "Quick search & actions"],
  ["g  c", "Command Center"],
  ["g  n", "New task"],
  ["g  g", "Task Graph"],
  ["g  l", "Lessons"],
  ["g  p", "Pipelines"],
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

/* ---------- the action palette (Ctrl/Cmd+K) ---------- */

type Kind = "command" | "page" | "task" | "action";
export interface PaletteItem {
  id: string;
  label: string;
  hint: string;
  kind: Kind;
  task?: Task;
  run: () => void | Promise<void>;
}

export type TaskAction =
  | "open" | "code" | "report" | "graph" | "copy" | "rerun" | "retry" | "cancel"
  | "watch-daily" | "watch-weekly" | "continue" | "ab";

const ACTION_LABEL: Record<TaskAction, string> = {
  open: "Open live workflow",
  code: "Open code",
  report: "Open final report",
  graph: "Show in Task Graph",
  copy: "Copy link",
  rerun: "Re-run as a regression check",
  retry: "Retry",
  cancel: "Cancel the run",
  "watch-daily": "Watch for regressions · daily",
  "watch-weekly": "Watch for regressions · weekly",
  continue: "Continue from this task",
  ab: "A/B test a model…",
};

/** What can be done with a task right now, given its status and the user's role. */
export function taskActions(t: Pick<Task, "status">, canDevelop: boolean): TaskAction[] {
  const out: TaskAction[] = ["open", "code", "report", "graph", "copy"];
  if (!canDevelop) return out;
  out.push(...actionsFor(t as Task));
  if (t.status === "COMPLETED") out.push("watch-daily", "watch-weekly", "continue", "ab");
  return out;
}

const RECENT_KEY = "lf-recent-tasks";
/** Remember a task the user opened (this tab only), most recent first, at most 5. */
export function rememberTask(id: string) {
  try {
    const prev: unknown = JSON.parse(sessionStorage.getItem(RECENT_KEY) ?? "[]");
    const list = Array.isArray(prev) ? prev.filter((x): x is string => typeof x === "string") : [];
    sessionStorage.setItem(RECENT_KEY, JSON.stringify([id, ...list.filter((x) => x !== id)].slice(0, 5)));
  } catch {
    /* storage unavailable: no recents, nothing else changes */
  }
}
export function recentIds(): string[] {
  try {
    const v: unknown = JSON.parse(sessionStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** Label with the matched characters in <mark>; rendered as text only. */
function Label({ text, indices }: { text: string; indices: number[] }) {
  if (!indices.length) return <>{text}</>;
  const hit = new Set(indices);
  const parts: { s: string; on: boolean }[] = [];
  for (let i = 0; i < text.length; i++) {
    const on = hit.has(i);
    const last = parts[parts.length - 1];
    if (last && last.on === on) last.s += text[i];
    else parts.push({ s: text[i], on });
  }
  return <>{parts.map((p, k) => (p.on ? <mark key={k}>{p.s}</mark> : <span key={k}>{p.s}</span>))}</>;
}

export function CommandPalette({
  open,
  onClose,
  onToggleTheme,
  onShortcuts,
  onSignOut,
}: {
  open: boolean;
  onClose: () => void;
  onToggleTheme?: () => void;
  onShortcuts?: () => void;
  onSignOut?: () => void;
}) {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [focus, setFocus] = useState<Task | null>(null); // showing one task's actions
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setSel(0);
    setFocus(null);
    input.current?.focus();
    api
      .get<Task[]>("/tasks", { limit: 50, order: "desc" })
      .then((t) => Array.isArray(t) && setTasks(t.filter((x) => x && typeof x.id === "string")))
      .catch(() => undefined);
  }, [open]);

  const back = () => {
    setFocus(null);
    setQ("");
    setSel(0);
    input.current?.focus();
  };

  const items = useMemo<PaletteItem[]>(() => {
    const go = (to: string, taskId?: string) => () => {
      if (taskId) rememberTask(taskId);
      navigate(to);
      onClose();
    };
    const call = (fn: () => Promise<unknown>, ok: string) => async () => {
      setBusy(true);
      try {
        await fn();
        toast(ok, "ok");
        onClose();
      } catch (e) {
        toast(e instanceof Error ? e.message : "That did not work", "bad");
      } finally {
        setBusy(false);
      }
    };
    const runFor = (t: Task, a: TaskAction): (() => void | Promise<void>) => {
      switch (a) {
        case "open": return go(`/tasks/${t.id}`, t.id);
        case "code": return go(`/tasks/${t.id}/code`, t.id);
        case "report":
        case "ab": return go(`/tasks/${t.id}/report`, t.id);
        case "graph": return go(`/graph?focus=${encodeURIComponent(`t:${t.id}`)}`, t.id);
        case "continue": return go(`/tasks/new?from=${t.id}`, t.id);
        case "copy": return call(() => navigator.clipboard.writeText(`${window.location.origin}/tasks/${t.id}`), "Link copied");
        case "rerun": return call(() => api.post(`/tasks/${t.id}/rerun`), "Re-run started");
        case "cancel": return call(() => api.post(`/tasks/${t.id}/cancel`), "Run cancelled");
        case "retry":
          return call(async () => {
            await api.post(`/tasks/${t.id}/retry`);
            await api.post(`/tasks/${t.id}/start`);
          }, "Retrying");
        case "watch-daily": return call(() => api.put(`/tasks/${t.id}/watch`, { interval_hours: 24, active: true }), "Watching daily");
        case "watch-weekly": return call(() => api.put(`/tasks/${t.id}/watch`, { interval_hours: 168, active: true }), "Watching weekly");
      }
    };

    if (focus) {
      return taskActions(focus, can("developer")).map((a) => ({
        id: `act:${a}`, label: ACTION_LABEL[a], hint: "action", kind: "action" as const, task: focus, run: runFor(focus, a),
      }));
    }
    const commands: PaletteItem[] = [];
    if (can("developer")) commands.push({ id: "cmd:new", label: "New task", hint: "command", kind: "command", run: go("/tasks/new") });
    if (onToggleTheme) commands.push({ id: "cmd:theme", label: "Toggle light / dark theme", hint: "command", kind: "command", run: () => { onToggleTheme(); onClose(); } });
    if (onShortcuts) commands.push({ id: "cmd:keys", label: "Show keyboard shortcuts", hint: "command", kind: "command", run: () => { onClose(); onShortcuts(); } });
    if (onSignOut) commands.push({ id: "cmd:out", label: "Sign out", hint: "command", kind: "command", run: () => { onClose(); onSignOut(); } });
    const pageList: [string, string][] = [
      ["Command Center", "/"], ["Task Graph", "/graph"], ["Lessons", "/lessons"], ["Pipelines", "/pipelines"], ["Loop Analytics", "/analytics"],
      ...(can("admin") ? ([["Admin", "/admin"]] as [string, string][]) : []),
      ["Settings", "/settings"],
    ];
    const pages: PaletteItem[] = pageList.map(([label, to]) => ({ id: `page:${to}`, label, hint: "page", kind: "page", run: go(to) }));
    const recent = recentIds();
    const order = (id: string) => (recent.includes(id) ? recent.indexOf(id) : 99);
    const taskItems: PaletteItem[] = [...tasks]
      .sort((a, b) => order(a.id) - order(b.id))
      .map((t) => ({
        id: `task:${t.id}`, label: t.requirement.slice(0, 80), kind: "task", task: t,
        hint: `${recent.includes(t.id) ? "recent · " : ""}${t.status.toLowerCase().replace(/_/g, " ")}`,
        run: go(`/tasks/${t.id}`, t.id),
      }));
    return [...taskItems.filter((t) => recent.includes(t.task!.id)), ...commands, ...pages, ...taskItems.filter((t) => !recent.includes(t.task!.id))];
  }, [focus, tasks, can, navigate, onClose, onToggleTheme, onShortcuts, onSignOut]);

  const commandMode = !focus && q.startsWith(">");
  const query = commandMode ? q.slice(1) : q;
  const pool = commandMode ? items.filter((i) => i.kind === "command") : items;
  const results = query.trim()
    ? rank(query, pool, (i) => i.label).slice(0, 9)
    : pool.slice(0, focus ? 20 : 9).map((item) => ({ item, hit: { score: 0, indices: [] as number[] } }));
  const current = results[Math.min(sel, results.length - 1)]?.item;

  if (!open) return null;
  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Quick search" onMouseDown={(e) => e.stopPropagation()}>
        {focus && (
          <div className="palette-crumb">
            <button type="button" className="link" onClick={back}>← All</button>
            <span className="palette-task">{focus.requirement}</span>
          </div>
        )}
        <input
          ref={input}
          value={q}
          placeholder={focus ? "What do you want to do with this task?" : "Search tasks and pages, or type > for commands…"}
          aria-label={focus ? "Search actions" : "Search pages and tasks"}
          onChange={(e) => {
            setQ(e.target.value);
            setSel(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              if (focus) back();
              else onClose();
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              setSel((s) => Math.min(s + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setSel((s) => Math.max(s - 1, 0));
            } else if ((e.key === "Tab" || e.key === "ArrowRight") && !e.shiftKey && current?.kind === "task" && current.task) {
              e.preventDefault();
              setFocus(current.task);
              setQ("");
              setSel(0);
            } else if (e.key === "Enter" && current && !busy) {
              e.preventDefault();
              void current.run();
            }
          }}
        />
        <ul>
          {results.map(({ item, hit }, n) => (
            <li key={item.id} className="palette-row">
              <button
                type="button"
                className={`${n === sel ? "on" : ""} pk-${item.kind}`}
                aria-label={`${item.label}, ${item.hint}`} // highlight spans would otherwise split the name
                onMouseEnter={() => setSel(n)}
                onClick={() => void item.run()}
                disabled={busy}
              >
                <span className="palette-label"><Label text={item.label} indices={hit.indices} /></span>
                <small>{item.hint}</small>
              </button>
              {item.kind === "task" && (
                <button
                  type="button"
                  className="palette-more"
                  title="Actions for this task (Tab)"
                  onClick={() => {
                    setFocus(item.task!);
                    setQ("");
                    setSel(0);
                    input.current?.focus();
                  }}
                >
                  Actions
                </button>
              )}
            </li>
          ))}
          {results.length === 0 && <li className="muted palette-none">No matches.</li>}
        </ul>
        <div className="palette-foot muted small" aria-hidden="true">
          <span><kbd>↑↓</kbd> move</span>
          <span><kbd>Enter</kbd> run</span>
          <span><kbd>Tab</kbd> task actions</span>
          <span><kbd>&gt;</kbd> commands</span>
          <span><kbd>Esc</kbd> {focus ? "back" : "close"}</span>
        </div>
      </div>
    </div>
  );
}
