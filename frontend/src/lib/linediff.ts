/**
 * Line diff (longest common subsequence) that emits unified-diff text with hunks and context,
 * so it renders through the existing DiffView. Used to compare two A/B runs' code in the browser.
 */

type Op = { k: " " | "-" | "+"; text: string };

const MAX_CELLS = 4_000_000; // guard: ~2000×2000 lines; beyond that fall back to a whole-file replace

function ops(a: string[], b: string[]): Op[] {
  // trim the common prefix/suffix first: most A/B files differ in a few places
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  const head: Op[] = a.slice(0, start).map((text) => ({ k: " ", text }));
  const tail: Op[] = a.slice(endA).map((text) => ({ k: " ", text }));
  const x = a.slice(start, endA);
  const y = b.slice(start, endB);
  const n = x.length;
  const m = y.length;
  let mid: Op[];
  if (n * m > MAX_CELLS) {
    mid = [...x.map((text) => ({ k: "-" as const, text })), ...y.map((text) => ({ k: "+" as const, text }))];
  } else {
    const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    mid = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (x[i] === y[j]) {
        mid.push({ k: " ", text: x[i] });
        i++;
        j++;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) mid.push({ k: "-", text: x[i++] });
      else mid.push({ k: "+", text: y[j++] });
    }
    while (i < n) mid.push({ k: "-", text: x[i++] });
    while (j < m) mid.push({ k: "+", text: y[j++] });
  }
  return [...head, ...mid, ...tail];
}

/** Unified diff of two texts ("" when identical). */
export function unifiedDiff(oldText: string, newText: string, oldName = "a", newName = "b", context = 3): string {
  if (oldText === newText) return "";
  const a = oldText === "" ? [] : oldText.split("\n");
  const b = newText === "" ? [] : newText.split("\n");
  const all = ops(a, b);
  const changed = all.map((o, idx) => (o.k !== " " ? idx : -1)).filter((idx) => idx >= 0);
  if (changed.length === 0) return "";
  // group changes into hunks with `context` lines around them
  const hunks: [number, number][] = [];
  for (const idx of changed) {
    const lo = Math.max(0, idx - context);
    const hi = Math.min(all.length - 1, idx + context);
    const last = hunks[hunks.length - 1];
    if (last && lo <= last[1] + 1) last[1] = Math.max(last[1], hi);
    else hunks.push([lo, hi]);
  }
  const out = [`--- ${oldName}`, `+++ ${newName}`];
  // line numbers at each op position
  let oldLine = 1;
  let newLine = 1;
  const pos = all.map((o) => {
    const p = { o: oldLine, n: newLine };
    if (o.k !== "+") oldLine++;
    if (o.k !== "-") newLine++;
    return p;
  });
  for (const [lo, hi] of hunks) {
    const slice = all.slice(lo, hi + 1);
    const oldCount = slice.filter((o) => o.k !== "+").length;
    const newCount = slice.filter((o) => o.k !== "-").length;
    out.push(`@@ -${oldCount ? pos[lo].o : pos[lo].o - 1},${oldCount} +${newCount ? pos[lo].n : pos[lo].n - 1},${newCount} @@`);
    for (const o of slice) out.push(o.k + o.text);
  }
  return out.join("\n") + "\n";
}

export type FileChange = "same" | "changed" | "only-a" | "only-b";

/** Compare two file listings by hash: which paths changed between run A and run B. */
export function compareListings(
  a: { path: string; sha256: string }[],
  b: { path: string; sha256: string }[],
): { path: string; change: FileChange }[] {
  const ma = new Map(a.map((f) => [f.path, f.sha256]));
  const mb = new Map(b.map((f) => [f.path, f.sha256]));
  const paths = [...new Set([...ma.keys(), ...mb.keys()])].sort();
  const rank: Record<FileChange, number> = { changed: 0, "only-a": 1, "only-b": 2, same: 3 };
  return paths
    .map((path) => ({
      path,
      change: (!mb.has(path) ? "only-a" : !ma.has(path) ? "only-b" : ma.get(path) === mb.get(path) ? "same" : "changed") as FileChange,
    }))
    .sort((x, y) => rank[x.change] - rank[y.change] || x.path.localeCompare(y.path));
}
