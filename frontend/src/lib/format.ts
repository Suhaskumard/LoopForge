/** Display helpers. `null` always renders as an em dash: "not computable", never a fake zero. */

export const DASH = "—";

export function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? DASH : `${v.toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined ? DASH : v.toFixed(digits);
}

export function seconds(v: number | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  if (v < 1) return `${Math.round(v * 1000)} ms`;
  if (v < 60) return `${v.toFixed(1)} s`;
  return `${Math.floor(v / 60)} m ${Math.round(v % 60)} s`;
}

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  return `$${v < 0.01 && v > 0 ? v.toFixed(5) : v.toFixed(3)}`;
}

export function score(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : `${Math.round(v * 100)}`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}
