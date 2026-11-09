/**
 * A small, dependency-free QR Code encoder (ISO/IEC 18004): byte mode, error correction level M,
 * versions 1-10 (up to 213 bytes, plenty for an otpauth:// URI). Output is a boolean module grid
 * (true = dark), rendered as SVG by the caller.
 *
 * Verified module-for-module against the python `qrcode` library (see __tests__/qr.test.ts and the
 * reference fixture), including its automatic mask choice.
 */

// [data codewords per block, number of blocks] groups and EC codewords per block, level M, v1-10
const BLOCKS_M: { ec: number; groups: [number, number][] }[] = [
  { ec: 10, groups: [[16, 1]] },
  { ec: 16, groups: [[28, 1]] },
  { ec: 26, groups: [[44, 1]] },
  { ec: 18, groups: [[32, 2]] },
  { ec: 24, groups: [[43, 2]] },
  { ec: 16, groups: [[27, 4]] },
  { ec: 18, groups: [[31, 4]] },
  { ec: 22, groups: [[38, 2], [39, 2]] },
  { ec: 22, groups: [[36, 3], [37, 2]] },
  { ec: 26, groups: [[43, 4], [44, 1]] },
];
const ALIGN: number[][] = [
  [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
];
const EC_LEVEL_M = 0b00;

/* ---------- GF(256) Reed-Solomon ---------- */

const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
{
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
}
const mul = (a: number, b: number) => (a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]]);

function generator(degree: number): number[] {
  let poly = [1];
  for (let i = 0; i < degree; i++) {
    const next = new Array(poly.length + 1).fill(0);
    for (let j = 0; j < poly.length; j++) {
      next[j] ^= poly[j];
      next[j + 1] ^= mul(poly[j], EXP[i]);
    }
    poly = next;
  }
  return poly; // highest degree first, leading 1
}

function ecCodewords(data: number[], degree: number): number[] {
  const gen = generator(degree);
  const rem = [...data, ...new Array(degree).fill(0)];
  for (let i = 0; i < data.length; i++) {
    const coef = rem[i];
    if (coef !== 0) for (let j = 1; j < gen.length; j++) rem[i + j] ^= mul(gen[j], coef);
  }
  return rem.slice(data.length);
}

/* ---------- data codewords ---------- */

const dataCapacity = (v: number) => BLOCKS_M[v - 1].groups.reduce((n, [d, c]) => n + d * c, 0);
const countBits = (v: number) => (v <= 9 ? 8 : 16);

export function pickVersion(byteLength: number): number {
  for (let v = 1; v <= 10; v++) if (4 + countBits(v) + 8 * byteLength <= dataCapacity(v) * 8) return v;
  throw new Error("text too long for a version 1-10 QR code");
}

function encodeData(bytes: Uint8Array, v: number): number[] {
  const bits: number[] = [];
  const put = (value: number, length: number) => {
    for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };
  put(0b0100, 4); // byte mode
  put(bytes.length, countBits(v));
  bytes.forEach((b) => put(b, 8));
  const limit = dataCapacity(v) * 8;
  if (bits.length + 4 <= limit) put(0, 4); // terminator
  while (bits.length % 8) bits.push(0);
  const words: number[] = [];
  for (let i = 0; i < bits.length; i += 8) words.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  for (let pad = 0xec; words.length < limit / 8; pad = pad === 0xec ? 0x11 : 0xec) words.push(pad);
  return words;
}

function interleave(data: number[], v: number): number[] {
  const { ec, groups } = BLOCKS_M[v - 1];
  const blocks: number[][] = [];
  let at = 0;
  for (const [size, count] of groups)
    for (let c = 0; c < count; c++) {
      blocks.push(data.slice(at, at + size));
      at += size;
    }
  const ecs = blocks.map((b) => ecCodewords(b, ec));
  const out: number[] = [];
  const longest = Math.max(...blocks.map((b) => b.length));
  for (let i = 0; i < longest; i++) for (const b of blocks) if (i < b.length) out.push(b[i]);
  for (let i = 0; i < ec; i++) for (const e of ecs) out.push(e[i]);
  return out;
}

/* ---------- matrix ---------- */

type Grid = (boolean | null)[][]; // null = not yet set (data area)

const degree = (x: number) => 31 - Math.clz32(x);
/** `data` followed by its BCH remainder modulo `poly` (systematic encoding). */
function bch(data: number, poly: number): number {
  const d = degree(poly);
  let rem = data << d;
  while (rem !== 0 && degree(rem) >= d) rem ^= poly << (degree(rem) - d);
  return (data << d) | rem;
}
export const formatBits = (mask: number) => bch((EC_LEVEL_M << 3) | mask, 0x537) ^ 0x5412;
export const versionBits = (v: number) => bch(v, 0x1f25);

function baseGrid(v: number): Grid {
  const n = 17 + 4 * v;
  const g: Grid = Array.from({ length: n }, () => new Array<boolean | null>(n).fill(null));
  const finder = (row: number, col: number) => {
    for (let r = -1; r <= 7; r++)
      for (let c = -1; c <= 7; c++) {
        const y = row + r;
        const x = col + c;
        if (y < 0 || y >= n || x < 0 || x >= n) continue;
        const ring = (r >= 0 && r <= 6 && (c === 0 || c === 6)) || (c >= 0 && c <= 6 && (r === 0 || r === 6));
        const core = r >= 2 && r <= 4 && c >= 2 && c <= 4;
        g[y][x] = ring || core;
      }
  };
  finder(0, 0);
  finder(n - 7, 0);
  finder(0, n - 7);
  for (const r of ALIGN[v - 1])
    for (const c of ALIGN[v - 1]) {
      if (g[r][c] !== null) continue; // overlaps a finder
      for (let dr = -2; dr <= 2; dr++)
        for (let dc = -2; dc <= 2; dc++)
          g[r + dr][c + dc] = Math.max(Math.abs(dr), Math.abs(dc)) !== 1;
    }
  for (let i = 8; i < n - 8; i++) {
    if (g[i][6] === null) g[i][6] = i % 2 === 0;
    if (g[6][i] === null) g[6][i] = i % 2 === 0;
  }
  return g;
}

/** Format info, version info and the dark module. `test` writes them light (as the reference does
 * while scoring masks), otherwise with their real values. */
function placeInfo(g: Grid, v: number, mask: number, test: boolean) {
  const n = g.length;
  const fb = formatBits(mask);
  for (let i = 0; i < 15; i++) {
    const on = !test && ((fb >> i) & 1) === 1;
    if (i < 6) g[i][8] = on;
    else if (i < 8) g[i + 1][8] = on;
    else g[n - 15 + i][8] = on;
    if (i < 8) g[8][n - i - 1] = on;
    else if (i < 9) g[8][15 - i] = on;
    else g[8][14 - i] = on;
  }
  g[n - 8][8] = !test;
  if (v >= 7) {
    const vb = versionBits(v);
    for (let i = 0; i < 18; i++) {
      const on = !test && ((vb >> i) & 1) === 1;
      g[Math.floor(i / 3)][(i % 3) + n - 11] = on;
      g[(i % 3) + n - 11][Math.floor(i / 3)] = on;
    }
  }
}

const MASKS: ((i: number, j: number) => boolean)[] = [
  (i, j) => (i + j) % 2 === 0,
  (i) => i % 2 === 0,
  (_, j) => j % 3 === 0,
  (i, j) => (i + j) % 3 === 0,
  (i, j) => (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0,
  (i, j) => ((i * j) % 2) + ((i * j) % 3) === 0,
  (i, j) => (((i * j) % 2) + ((i * j) % 3)) % 2 === 0,
  (i, j) => (((i * j) % 3) + ((i + j) % 2)) % 2 === 0,
];

function placeData(g: Grid, codewords: number[], mask: number) {
  const n = g.length;
  const fn = MASKS[mask];
  let row = n - 1;
  let inc = -1;
  let byte = 0;
  let bit = 7;
  for (let col = n - 1; col > 0; col -= 2) {
    if (col <= 6) col -= 1;
    for (;;) {
      for (const c of [col, col - 1]) {
        if (g[row][c] !== null) continue;
        let dark = byte < codewords.length ? ((codewords[byte] >> bit) & 1) === 1 : false;
        if (fn(row, c)) dark = !dark;
        g[row][c] = dark;
        if (--bit === -1) {
          byte++;
          bit = 7;
        }
      }
      row += inc;
      if (row < 0 || row >= n) {
        row -= inc;
        inc = -inc;
        break;
      }
    }
    if (col <= 6) col += 1; // undo the timing-column shift for the loop arithmetic
  }
}

/** Penalty score, same rules (and the same scanning) as the python `qrcode` library. */
export function penalty(m: boolean[][]): number {
  const n = m.length;
  let lost = 0;
  const runs = (get: (a: number, b: number) => boolean) => {
    for (let a = 0; a < n; a++) {
      let prev = get(a, 0);
      let len = 0;
      for (let b = 0; b < n; b++) {
        if (get(a, b) === prev) len++;
        else {
          if (len >= 5) lost += len - 2;
          len = 1;
          prev = get(a, b);
        }
      }
      if (len >= 5) lost += len - 2;
    }
  };
  runs((r, c) => m[r][c]);
  runs((c, r) => m[r][c]);
  for (let r = 0; r < n - 1; r++)
    for (let c = 0; c < n - 1; c++) {
      const v = m[r][c];
      if (m[r][c + 1] === v && m[r + 1][c] === v && m[r + 1][c + 1] === v) lost += 3;
    }
  const finderLike = (get: (a: number, b: number) => boolean) => {
    for (let a = 0; a < n; a++) {
      for (let b = 0; b < n - 10; b++) {
        const x = (k: number) => get(a, b + k);
        if (
          !x(1) && x(4) && !x(5) && x(6) && !x(9) &&
          ((x(0) && x(2) && x(3) && !x(7) && !x(8) && !x(10)) || (!x(0) && !x(2) && !x(3) && x(7) && x(8) && x(10)))
        )
          lost += 40;
        if (x(10)) b++; // the reference skips the next start position here
      }
    }
  };
  finderLike((r, c) => m[r][c]);
  finderLike((c, r) => m[r][c]);
  let dark = 0;
  for (const row of m) for (const v of row) if (v) dark++;
  lost += Math.floor(Math.abs((dark / (n * n)) * 100 - 50) / 5) * 10;
  return lost;
}

function build(codewords: number[], v: number, mask: number, test: boolean): boolean[][] {
  const g = baseGrid(v);
  placeInfo(g, v, mask, true); // reserve the info areas before the data is placed
  placeData(g, codewords, mask);
  placeInfo(g, v, mask, test);
  return g as boolean[][];
}

export interface QrCode {
  version: number;
  mask: number;
  modules: boolean[][];
}

/** Encode `text` (UTF-8). `mask` forces a mask pattern; by default the lowest-penalty one is used. */
export function encodeQr(text: string, mask?: number): QrCode {
  const bytes = new TextEncoder().encode(text);
  const version = pickVersion(bytes.length);
  const codewords = interleave(encodeData(bytes, version), version);
  let chosen = mask ?? -1;
  if (chosen < 0) {
    let best = Infinity;
    for (let k = 0; k < 8; k++) {
      const score = penalty(build(codewords, version, k, true));
      if (score < best) {
        best = score;
        chosen = k;
      }
    }
  }
  return { version, mask: chosen, modules: build(codewords, version, chosen, false) };
}
