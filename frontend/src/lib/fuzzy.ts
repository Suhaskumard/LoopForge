/**
 * Subsequence fuzzy matching for the command palette: every query character must appear in order.
 * Scores favour matches at word starts, consecutive runs and early positions; returns the matched
 * character positions so the caller can highlight them (as text spans, never HTML).
 */
export interface FuzzyHit {
  score: number;
  indices: number[];
}

const isWordStart = (text: string, i: number) => i === 0 || /[\s/_.\-·:]/.test(text[i - 1]);

export function fuzzy(query: string, text: string): FuzzyHit | null {
  const q = query.trim().toLowerCase();
  if (!q) return { score: 0, indices: [] };
  const t = text.toLowerCase();
  // fast path: a plain substring is the best kind of match
  const at = t.indexOf(q);
  if (at >= 0) {
    return {
      score: 1000 - at + (isWordStart(text, at) ? 200 : 0) + q.length * 10,
      indices: Array.from({ length: q.length }, (_, k) => at + k),
    };
  }
  const indices: number[] = [];
  let score = 0;
  let from = 0;
  for (const ch of q) {
    if (ch === " ") continue;
    // prefer the next occurrence that starts a word, else the next one at all
    let pick = -1;
    for (let i = from; i < t.length; i++) {
      if (t[i] !== ch) continue;
      if (isWordStart(text, i)) {
        pick = i;
        break;
      }
      if (pick < 0) pick = i;
    }
    if (pick < 0) return null;
    const prev = indices[indices.length - 1];
    score += isWordStart(text, pick) ? 30 : 0;
    score += prev !== undefined && pick === prev + 1 ? 20 : 0;
    score -= Math.min(10, pick - from);
    indices.push(pick);
    from = pick + 1;
  }
  return { score, indices };
}

/** Rank `items` by `label(item)` against the query; non-matches are dropped. Stable for ties. */
export function rank<T>(query: string, items: T[], label: (t: T) => string): { item: T; hit: FuzzyHit }[] {
  return items
    .map((item, order) => ({ item, hit: fuzzy(query, label(item)), order }))
    .filter((x): x is { item: T; hit: FuzzyHit; order: number } => x.hit !== null)
    .sort((a, b) => b.hit.score - a.hit.score || a.order - b.order)
    .map(({ item, hit }) => ({ item, hit }));
}
