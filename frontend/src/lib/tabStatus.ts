import { useEffect } from "react";

/** Draws the LoopForge mark with a coloured status dot, as a favicon data URL. */
function iconWithDot(color: string): string {
  const svg =
    `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>` +
    `<circle cx='14' cy='16' r='11' fill='none' stroke='#8b7bff' stroke-width='4'/>` +
    `<circle cx='14' cy='16' r='3.5' fill='#38d5f5'/>` +
    `<circle cx='25' cy='7' r='6.5' fill='${color}' stroke='#0a0b10' stroke-width='2'/></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

const COLOR = { running: "#38d5f5", ok: "#4ade9a", bad: "#ff7b7b" } as const;

/**
 * While a task page is open, reflect its state in the browser tab: a status dot on the favicon and a
 * prefix on the title. Everything is restored when the page unmounts or the state clears.
 */
export function useTabStatus(state: keyof typeof COLOR | null, label: string) {
  useEffect(() => {
    if (!state) return;
    const link = document.querySelector<HTMLLinkElement>("link[rel='icon']");
    const oldHref = link?.href;
    const oldTitle = document.title;
    if (link) link.href = iconWithDot(COLOR[state]);
    document.title = `${state === "running" ? "●" : state === "ok" ? "✓" : "✕"} ${label} · LoopForge`;
    return () => {
      if (link && oldHref) link.href = oldHref;
      document.title = oldTitle;
    };
  }, [state, label]);
}
