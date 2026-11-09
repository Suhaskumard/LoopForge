/**
 * A tiny, dependency-free tokenizer for code display. It only classifies text: the result is rendered
 * as React text nodes, never as HTML, so generated (untrusted) code cannot inject markup.
 */
export type TokenKind = "kw" | "str" | "com" | "num" | "fn" | "dec" | "bi" | "txt";
export interface Token {
  text: string;
  kind: TokenKind;
}
export type Lang = "python" | "js" | "plain";

const PY_KW = new Set(
  "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield match case".split(" "),
);
const JS_KW = new Set(
  "await break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof let new null return super switch this throw true try typeof undefined var void while with yield async of interface type enum implements".split(" "),
);
const PY_BI = new Set("print len range str int float dict list set tuple bool self cls isinstance super open enumerate zip map filter sorted any all min max sum".split(" "));
const JS_BI = new Set("console window document Math JSON Promise Array Object String Number Boolean Map Set Error require module".split(" "));

export function langOf(path: string | null | undefined): Lang {
  const ext = path?.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "py" || ext === "pyi") return "python";
  if (["js", "jsx", "ts", "tsx", "mjs", "cjs"].includes(ext)) return "js";
  return "plain";
}

export const LANG_LABEL: Record<Lang, string> = { python: "Python", js: "JavaScript / TypeScript", plain: "Plain text" };

// one alternation, tried left to right at each position
const PY_RE = /(#.*$)|("""[\s\S]*?"""|'''[\s\S]*?'''|[rbfu]{0,2}"(?:\\.|[^"\\])*"|[rbfu]{0,2}'(?:\\.|[^'\\])*')|(@[\w.]+)|(\b\d[\d_]*(?:\.\d+)?(?:e[+-]?\d+)?\b)|([A-Za-z_]\w*)(?=\s*\()|([A-Za-z_]\w*)/gm;
const JS_RE = /(\/\/.*$|\/\*[\s\S]*?\*\/)|(`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(@[\w.]+)|(\b\d[\d_]*(?:\.\d+)?(?:e[+-]?\d+)?\b)|([A-Za-z_$][\w$]*)(?=\s*\()|([A-Za-z_$][\w$]*)/gm;

/** Tokenize one line. Multi-line strings/comments are approximated per line, which is fine for display. */
export function tokenizeLine(line: string, lang: Lang): Token[] {
  if (lang === "plain" || line === "") return [{ text: line, kind: "txt" }];
  const re = new RegExp(lang === "python" ? PY_RE.source : JS_RE.source, "gm");
  const kw = lang === "python" ? PY_KW : JS_KW;
  const bi = lang === "python" ? PY_BI : JS_BI;
  const out: Token[] = [];
  let last = 0;
  const push = (text: string, kind: TokenKind) => {
    if (!text) return;
    const prev = out[out.length - 1];
    if (prev && prev.kind === kind) prev.text += text;
    else out.push({ text, kind });
  };
  for (let m = re.exec(line); m; m = re.exec(line)) {
    if (m[0] === "") {
      re.lastIndex++;
      continue;
    }
    push(line.slice(last, m.index), "txt");
    const [, com, str, dec, num, fn, word] = m;
    if (com) push(com, "com");
    else if (str) push(str, "str");
    else if (dec) push(dec, "dec");
    else if (num) push(num, "num");
    else if (fn) push(fn, kw.has(fn) ? "kw" : bi.has(fn) ? "bi" : "fn");
    else if (word) push(word, kw.has(word) ? "kw" : bi.has(word) ? "bi" : "txt");
    last = m.index + m[0].length;
  }
  push(line.slice(last), "txt");
  return out;
}

/** The most "interesting" token kind of a line, used to color its minimap bar. */
export function dominantKind(tokens: Token[]): TokenKind {
  let best: TokenKind = "txt";
  let size = 0;
  for (const t of tokens) {
    if (t.kind === "txt") continue;
    if (t.text.length > size) {
      size = t.text.length;
      best = t.kind;
    }
  }
  return best;
}
