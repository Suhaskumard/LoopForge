import { useEffect, useMemo, useState } from "react";
import type { LiveEvent } from "../api/types";
import { initialLive, reduceEvent, type LiveState } from "../lib/events";

/** The view state after the first `cursor` events: the same fold the live stream uses. */
export function foldTo(events: LiveEvent[], cursor: number): LiveState {
  return events.slice(0, Math.max(0, cursor)).reduce(reduceEvent, initialLive());
}

const SPEEDS = [1, 4, 16] as const;

/**
 * Run Replay: scrub or play a finished run's history. While active, the page renders the folded
 * historical state instead of the live one, so every panel (reactor, rail, graph, timeline) replays.
 */
export function useReplay(events: LiveEvent[]) {
  const [cursor, setCursor] = useState<number | null>(null); // null = not replaying (live view)
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(4);
  const total = events.length;

  useEffect(() => {
    if (!playing || cursor === null) return;
    if (cursor >= total) {
      setPlaying(false);
      return;
    }
    const t = window.setTimeout(() => setCursor((c) => Math.min(total, (c ?? 0) + 1)), 900 / speed);
    return () => window.clearTimeout(t);
  }, [playing, cursor, total, speed]);

  const state = useMemo(() => (cursor === null ? null : foldTo(events, cursor)), [events, cursor]);
  return {
    active: cursor !== null,
    cursor: cursor ?? total,
    total,
    playing,
    speed,
    state,
    start: () => {
      setCursor(0);
      setPlaying(true);
    },
    stop: () => {
      setCursor(null);
      setPlaying(false);
    },
    toggle: () => {
      if (cursor !== null && cursor >= total) setCursor(0);
      setPlaying((p) => !p);
    },
    seek: (n: number) => {
      setCursor(Math.max(0, Math.min(total, n)));
    },
    cycleSpeed: () => setSpeed((s) => SPEEDS[(SPEEDS.indexOf(s) + 1) % SPEEDS.length]),
  };
}

export function ReplayBar({ replay, events }: { replay: ReturnType<typeof useReplay>; events: LiveEvent[] }) {
  const current = events[replay.cursor - 1];
  return (
    <section className={`replay${replay.active ? " on" : ""}`} aria-label="Run replay">
      {!replay.active ? (
        <>
          <span className="replay-title"><span aria-hidden="true">⏮</span> Run replay</span>
          <span className="muted small">Watch this run again, step by step: {events.length} events.</span>
          <button type="button" className="primary" onClick={replay.start}>Replay run</button>
        </>
      ) : (
        <>
          <button type="button" className="replay-btn" onClick={replay.toggle} aria-label={replay.playing ? "Pause replay" : "Play replay"}>
            {replay.playing ? "❚❚" : "▶"}
          </button>
          <button type="button" className="replay-btn" onClick={() => replay.seek(replay.cursor - 1)} aria-label="Step back">⏴</button>
          <button type="button" className="replay-btn" onClick={() => replay.seek(replay.cursor + 1)} aria-label="Step forward">⏵</button>
          <input
            type="range"
            min={0}
            max={replay.total}
            value={replay.cursor}
            onChange={(e) => replay.seek(Number(e.target.value))}
            aria-label="Replay position"
            style={{ "--fill": `${replay.total ? (replay.cursor / replay.total) * 100 : 0}%` } as React.CSSProperties}
          />
          <span className="replay-pos mono small">{replay.cursor}/{replay.total}</span>
          <button type="button" className="replay-btn speed" onClick={replay.cycleSpeed} aria-label={`Speed ${replay.speed}x`}>{replay.speed}×</button>
          <span className="replay-now small">{current ? current.event.replace(/_/g, " ") + (current.agent ? ` · ${current.agent}` : "") : "start"}</span>
          <button type="button" className="link" onClick={replay.stop}>Back to live</button>
        </>
      )}
    </section>
  );
}
