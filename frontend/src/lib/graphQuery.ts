import type { GraphEdge, GraphNode } from "../api/types";

export function adjacency(edges: GraphEdge[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  const add = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set());
    adj.get(a)!.add(b);
  };
  for (const e of edges) {
    add(e.source, e.target);
    add(e.target, e.source);
  }
  return adj;
}

/** The node plus everything directly connected to it. */
export function neighbourhood(id: string, adj: Map<string, Set<string>>): Set<string> {
  return new Set([id, ...(adj.get(id) ?? [])]);
}

/** Shortest path (fewest hops, undirected) from `from` to `to`, or [] when they are not connected. */
export function shortestPath(from: string, to: string, adj: Map<string, Set<string>>): string[] {
  if (from === to) return [from];
  const prev = new Map<string, string>([[from, from]]);
  const queue = [from];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const next of adj.get(cur) ?? []) {
      if (prev.has(next)) continue;
      prev.set(next, cur);
      if (next === to) {
        const path = [to];
        let at = to;
        while (at !== from) {
          at = prev.get(at)!;
          path.unshift(at);
        }
        return path;
      }
      queue.push(next);
    }
  }
  return [];
}

/** Rank nodes against a free-text query: exact label > prefix > word prefix > substring; status matches too. */
export function search(nodes: GraphNode[], query: string): GraphNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored: [number, GraphNode][] = [];
  for (const n of nodes) {
    const label = n.label.toLowerCase();
    const status = (n.status ?? "").toLowerCase();
    let score = 0;
    if (label === q) score = 100;
    else if (label.startsWith(q)) score = 80;
    else if (label.split(/[\s/_.-]+/).some((w) => w.startsWith(q))) score = 60;
    else if (label.includes(q)) score = 40;
    else if (status && status.replace(/_/g, " ").includes(q)) score = 30;
    else if (n.type.startsWith(q)) score = 10;
    if (score) scored.push([score + (n.type === "task" ? 2 : 0), n]);
  }
  return scored.sort((a, b) => b[0] - a[0] || a[1].label.localeCompare(b[1].label)).map(([, n]) => n);
}

/** Path segments as edge keys "a|b" (both directions), for highlighting. */
export function pathEdges(path: string[]): Set<string> {
  const keys = new Set<string>();
  for (let i = 1; i < path.length; i++) {
    keys.add(`${path[i - 1]}|${path[i]}`);
    keys.add(`${path[i]}|${path[i - 1]}`);
  }
  return keys;
}
