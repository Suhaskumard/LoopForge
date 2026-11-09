import { useMemo } from "react";

const COLORS = ["#8b7bff", "#38d5f5", "#4ade9a", "#fbbf4a", "#ff8a3d", "#ff7bd5"];

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** A one-shot burst of CSS particles. Purely decorative; nothing renders when reduced motion is requested. */
export function Confetti({ count = 48 }: { count?: number }) {
  const pieces = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => ({
        left: Math.random() * 100,
        delay: Math.random() * 0.5,
        duration: 1.8 + Math.random() * 1.6,
        drift: (Math.random() - 0.5) * 220,
        spin: (Math.random() - 0.5) * 1080,
        color: COLORS[i % COLORS.length],
        round: i % 3 === 0,
      })),
    [count],
  );
  if (prefersReducedMotion()) return null;
  return (
    <div className="confetti" aria-hidden="true" data-testid="confetti">
      {pieces.map((p, i) => (
        <i
          key={i}
          className={p.round ? "round" : ""}
          style={
            {
              left: `${p.left}%`,
              background: p.color,
              animationDelay: `${p.delay}s`,
              animationDuration: `${p.duration}s`,
              "--drift": `${p.drift}px`,
              "--spin": `${p.spin}deg`,
            } as React.CSSProperties
          }
        />
      ))}
    </div>
  );
}
