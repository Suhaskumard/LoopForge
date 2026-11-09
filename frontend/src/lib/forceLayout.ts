/**
 * A small, deterministic force-directed layout (no dependencies).
 * Repulsion between all nodes, springs along edges, gentle pull to the centre. The same input always
 * produces the same positions (seeded start + fixed number of ticks), so the map is stable between visits.
 */

export interface LayoutNode {
  id: string;
  weight?: number; // heavier nodes push harder and move less (project hubs)
}
export interface LayoutEdge {
  source: string;
  target: string;
  length?: number;
}
export type Positions = Record<string, { x: number; y: number }>;

function seeded(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

export function forceLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  { ticks = 260, spread = 900 }: { ticks?: number; spread?: number } = {},
): Positions {
  const n = nodes.length;
  if (n === 0) return {};
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const rand = seeded(hash(nodes.map((x) => x.id).join("|")));
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  const vx = new Float64Array(n);
  const vy = new Float64Array(n);
  const w = nodes.map((node) => node.weight ?? 1);
  const radius = Math.sqrt(n) * 40;
  for (let i = 0; i < n; i++) {
    const a = rand() * Math.PI * 2;
    const r = radius * Math.sqrt(rand());
    x[i] = Math.cos(a) * r;
    y[i] = Math.sin(a) * r;
  }
  const links = edges
    .map((e) => ({ a: index.get(e.source), b: index.get(e.target), len: e.length ?? 110 }))
    .filter((l): l is { a: number; b: number; len: number } => l.a !== undefined && l.b !== undefined && l.a !== l.b);

  const repulse = 5200;
  for (let t = 0; t < ticks; t++) {
    const cool = 1 - t / ticks;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = x[i] - x[j];
        let dy = y[i] - y[j];
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) {
          dx = rand() - 0.5;
          dy = rand() - 0.5;
          d2 = 1;
        }
        if (d2 > 640000) continue; // far apart: ignore (keeps it O(n²) but cheap)
        const f = (repulse * w[i] * w[j]) / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        vx[i] += fx / w[i];
        vy[i] += fy / w[i];
        vx[j] -= fx / w[j];
        vy[j] -= fy / w[j];
      }
    }
    for (const { a, b, len } of links) {
      const dx = x[b] - x[a];
      const dy = y[b] - y[a];
      const d = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const f = (d - len) * 0.04;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      vx[a] += fx / w[a];
      vy[a] += fy / w[a];
      vx[b] -= fx / w[b];
      vy[b] -= fy / w[b];
    }
    for (let i = 0; i < n; i++) {
      vx[i] -= x[i] * 0.004;
      vy[i] -= y[i] * 0.004;
      const step = 12 * cool + 0.5;
      const sp = Math.sqrt(vx[i] * vx[i] + vy[i] * vy[i]);
      const k = sp > step ? step / sp : 1;
      x[i] += vx[i] * k;
      y[i] += vy[i] * k;
      vx[i] *= 0.6;
      vy[i] *= 0.6;
    }
  }
  // scale into a predictable box
  let max = 1;
  for (let i = 0; i < n; i++) max = Math.max(max, Math.abs(x[i]), Math.abs(y[i]));
  const s = n === 1 ? 0 : Math.min(1, spread / 2 / max);
  const out: Positions = {};
  nodes.forEach((node, i) => (out[node.id] = { x: Math.round(x[i] * s), y: Math.round(y[i] * s) }));
  return out;
}
