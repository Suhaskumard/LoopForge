import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "loopforge-theme";

function stored(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "dark" || v === "light" ? v : null;
  } catch {
    return null;
  }
}

function effective(): Theme {
  return stored() ?? (window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark");
}

/** Applies a saved choice to <html> before first paint (call once from main.tsx). */
export function initTheme() {
  const t = stored();
  if (t) document.documentElement.dataset.theme = t;
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(effective);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try {
        window.localStorage.setItem(KEY, next);
      } catch {
        /* storage unavailable: the choice just lasts for this visit */
      }
      return next;
    });
  }, []);
  return [theme, toggle];
}
