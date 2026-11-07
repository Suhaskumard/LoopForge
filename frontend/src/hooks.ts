import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { AgentRun, Iteration, LiveEvent, Task } from "./api/types";
import { isTerminal } from "./api/types";
import { eventsFromRuns, initialLive, reduceEvent, type LiveState } from "./lib/events";

export interface AsyncState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/** Fetch on mount/dependency change. Stale responses (older request) are discarded. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const latest = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    const id = ++latest.current;
    setLoading(true);
    fnRef
      .current()
      .then((d) => {
        if (id === latest.current) {
          setData(d);
          setError(undefined);
        }
      })
      .catch((e: unknown) => {
        if (id === latest.current) setError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (id === latest.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, error, loading, reload: useCallback(() => setTick((t) => t + 1), []) };
}

export type Connection = "connecting" | "live" | "polling" | "closed";

const MAX_WS_FAILURES = 3;

/**
 * Live task events over WebSocket with automatic reconnect. The server replays history on every
 * connect and events carry stable ids, so a reconnect can never drop or duplicate a step. After
 * repeated socket failures the hook falls back to polling the REST endpoints.
 */
export function useTaskEvents(taskId: string): {
  live: LiveState;
  connection: Connection;
  reconnect: () => void;
} {
  const [live, setLive] = useState<LiveState>(initialLive);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [session, setSession] = useState(0);

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let poll: ReturnType<typeof setInterval> | undefined;
    let failures = 0;
    setLive(initialLive());
    setConnection("connecting");

    const apply = (events: LiveEvent[]) =>
      setLive((s) => events.reduce((acc, e) => reduceEvent(acc, e), s));

    const startPolling = () => {
      if (poll) return;
      setConnection("polling");
      const tick = async () => {
        try {
          const [task, runs, its] = await Promise.all([
            api.get<Task>(`/tasks/${taskId}`),
            api.get<AgentRun[]>(`/tasks/${taskId}/agent-runs`),
            api.get<Iteration[]>(`/tasks/${taskId}/iterations`),
          ]);
          if (stopped) return;
          apply(eventsFromRuns(taskId, runs, its));
          if (isTerminal(task.status)) {
            setLive((s) => ({ ...s, terminal: task.status }));
            clearInterval(poll);
            setConnection("closed");
          }
        } catch {
          /* keep polling */
        }
      };
      void tick();
      poll = setInterval(() => void tick(), 2000);
    };

    const connect = async () => {
      const token = await api.accessToken();
      if (stopped) return;
      if (!token) return setConnection("closed");
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${window.location.host}/ws/tasks/${taskId}?token=${encodeURIComponent(token)}`);
      socket.onopen = () => {
        failures = 0;
        if (poll) clearInterval(poll);
        poll = undefined;
        setConnection("live");
      };
      socket.onmessage = (m) => apply([JSON.parse(m.data as string) as LiveEvent]);
      socket.onclose = (ev) => {
        if (stopped) return;
        if (ev.code === 1000 || ev.code === 4404) return setConnection("closed");
        failures += 1;
        if (failures >= MAX_WS_FAILURES) startPolling();
        retry = setTimeout(() => void connect(), Math.min(1000 * 2 ** failures, 10000));
      };
    };

    void connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      if (poll) clearInterval(poll);
      socket?.close();
    };
  }, [taskId, session]);

  return { live, connection, reconnect: useCallback(() => setSession((n) => n + 1), []) };
}
