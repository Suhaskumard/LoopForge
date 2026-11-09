/**
 * Lightweight requirement similarity (no model, no server): TF-IDF weighted cosine over word stems.
 * Good enough to say "you asked for something like this before" and to forecast from those runs.
 */

const STOP = new Set(
  "a an the and or of to for with in on at by from as is are be it this that these those into over under using use build write create make add implement should must can will which who whose each every all any plus also then than so such its their".split(" "),
);

export function terms(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9/{}_\s-]/g, " ")
    .split(/[\s/_-]+/)
    .map((w) => w.replace(/[{}]/g, ""))
    .filter((w) => w.length > 2 && !STOP.has(w))
    .map((w) => w.replace(/(ing|ed|es|s)$/, "")) // crude stemming: tests→test, endpoints→endpoint
    .filter((w) => w.length > 2);
}

export interface Doc<T> {
  item: T;
  text: string;
}

export function rankSimilar<T>(query: string, docs: Doc<T>[], limit = 3, min = 0.12): { item: T; score: number }[] {
  const q = terms(query);
  if (q.length < 2 || docs.length === 0) return [];
  const docTerms = docs.map((d) => terms(d.text));
  const df = new Map<string, number>();
  for (const ts of docTerms) for (const t of new Set(ts)) df.set(t, (df.get(t) ?? 0) + 1);
  const n = docs.length;
  const idf = (t: string) => Math.log(1 + n / (1 + (df.get(t) ?? 0)));
  const vec = (ts: string[]) => {
    const tf = new Map<string, number>();
    for (const t of ts) tf.set(t, (tf.get(t) ?? 0) + 1);
    const v = new Map<string, number>();
    for (const [t, c] of tf) v.set(t, c * idf(t));
    return v;
  };
  const norm = (v: Map<string, number>) => Math.sqrt([...v.values()].reduce((s, x) => s + x * x, 0)) || 1;
  const qv = vec(q);
  const qn = norm(qv);
  return docTerms
    .map((ts, i) => {
      const dv = vec(ts);
      let dot = 0;
      for (const [t, w] of qv) dot += w * (dv.get(t) ?? 0);
      return { item: docs[i].item, score: dot / (qn * norm(dv)) };
    })
    .filter((r) => r.score >= min)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}

export interface Forecast {
  basis: number; // finished similar tasks used
  acceptRate: number | null; // 0..1
  avgIterations: number | null;
}

/** What similar finished tasks suggest about this one. */
export function forecast(similar: { status: string; current_iteration: number }[]): Forecast {
  const done = similar.filter((t) => ["COMPLETED", "FAILED", "ESCALATED"].includes(t.status));
  if (done.length === 0) return { basis: 0, acceptRate: null, avgIterations: null };
  const ok = done.filter((t) => t.status === "COMPLETED");
  return {
    basis: done.length,
    acceptRate: ok.length / done.length,
    avgIterations: ok.length ? ok.reduce((s, t) => s + t.current_iteration, 0) / ok.length : null,
  };
}
