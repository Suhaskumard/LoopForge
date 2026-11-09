import { useEffect, useState } from "react";

type Kind = "ok" | "bad" | "info";
interface ToastItem {
  id: number;
  text: string;
  kind: Kind;
}

const EVENT = "loopforge:toast";
let seq = 0;

/** Show a short message in the corner. Works from anywhere; <Toaster /> (in the layout) renders it. */
export function toast(text: string, kind: Kind = "info") {
  window.dispatchEvent(new CustomEvent<ToastItem>(EVENT, { detail: { id: ++seq, text, kind } }));
}

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);
  useEffect(() => {
    const timers: number[] = [];
    const add = (e: Event) => {
      const item = (e as CustomEvent<ToastItem>).detail;
      setItems((list) => [...list.slice(-3), item]);
      timers.push(window.setTimeout(() => setItems((list) => list.filter((t) => t.id !== item.id)), 3800));
    };
    window.addEventListener(EVENT, add);
    return () => {
      window.removeEventListener(EVENT, add);
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          <span className="toast-dot" aria-hidden="true" />
          {t.text}
        </div>
      ))}
    </div>
  );
}
