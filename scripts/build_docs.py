"""Build the documentation site and check every link (Phase 18).

    python scripts/build_docs.py            # check links, then write docs/_site/ (static HTML, no server needed)
    python scripts/build_docs.py --check    # only check (what the gate and the test run)

Pages: docs/index.md, every docs/*.md, docs/tutorials/*.md, docs/adr/*.md, docs/pentest/*.md, README.md, CHANGELOG.md.
The check fails on: a relative link to a file that does not exist, a `#anchor` that is not a heading in the target page, an
image that does not exist, and a page that is not reachable from docs/index.md (an orphan nobody can find).
It does NOT check external http(s) links (no network assumptions) or that the prose is correct.
"""

import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITE = DOCS / "_site"
INDEX = DOCS / "index.md"
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(```|~~~)")


def pages() -> list[Path]:
    found = [ROOT / "README.md", ROOT / "CHANGELOG.md"]
    for pattern in ("*.md", "tutorials/*.md", "adr/*.md", "pentest/*.md"):
        found.extend(sorted(DOCS.glob(pattern)))
    return [p for p in found if p.exists()]


def slug(heading: str) -> str:
    """The anchor the `toc` extension generates, so links written for GitHub also work here."""
    text = re.sub(r"[`*_]", "", heading)
    text = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE).strip()
    return re.sub(r"[\s]+", "-", text)


def strip_code(md: str) -> str:
    out, fenced = [], False
    for line in md.split("\n"):
        if FENCE.match(line.strip()):
            fenced = not fenced
            continue
        if not fenced:
            out.append(re.sub(r"`[^`]*`", "", line))  # inline code can contain brackets that look like links
    return "\n".join(out)


def anchors_of(md: str) -> set[str]:
    seen: dict[str, int] = {}
    found = set()
    fenced = False
    for line in md.split("\n"):
        if FENCE.match(line.strip()):
            fenced = not fenced
        m = None if fenced else re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            seen[s] = n + 1
            found.add(s if n == 0 else f"{s}_{n}")
    return found


def links_of(md: str) -> list[tuple[str, str]]:
    text = strip_code(md)
    return [("link", m) for m in LINK.findall(text)] + [("image", m) for m in IMAGE.findall(text)]


def check() -> tuple[list[str], dict[Path, set[Path]]]:
    problems: list[str] = []
    graph: dict[Path, set[Path]] = {}
    texts = {p: p.read_text(encoding="utf-8") for p in pages()}
    anchors = {p: anchors_of(t) for p, t in texts.items()}
    for page, text in texts.items():
        graph[page] = set()
        for kind, target in links_of(text):
            parts = urlsplit(target)
            if parts.scheme in ("http", "https", "mailto"):
                continue
            dest = page if not parts.path else (page.parent / unquote(parts.path)).resolve()
            rel = page.relative_to(ROOT).as_posix()
            if not dest.exists():
                problems.append(f"{rel}: {kind} to missing file '{target}'")
                continue
            if dest.suffix == ".md":
                graph[page].add(dest)
                if parts.fragment and parts.fragment not in anchors.get(dest, anchors_of(dest.read_text(encoding='utf-8'))):
                    problems.append(f"{rel}: '{target}' - no such heading in {dest.relative_to(ROOT).as_posix()}")
    if INDEX.exists():
        reachable, stack = set(), [INDEX]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            stack.extend(graph.get(cur, ()))
        for p in pages():
            if p not in reachable and p != INDEX:
                problems.append(f"{p.relative_to(ROOT).as_posix()}: not reachable from docs/index.md (orphan page)")
    else:
        problems.append("docs/index.md is missing")
    return problems, graph


def render() -> int:
    import markdown

    SITE.mkdir(exist_ok=True)
    nav = [(p, (p.read_text(encoding="utf-8").split("\n", 1)[0].lstrip("# ").strip() or p.stem)) for p in pages()]
    count = 0
    for page, title in nav:
        out = SITE / _out_name(page)
        body = markdown.markdown(
            page.read_text(encoding="utf-8"), extensions=["fenced_code", "tables", "toc", "sane_lists"]
        )
        body = re.sub(r'href="([^"#]*?)\.md(#[^"]*)?"', lambda m: _fix_href(page, m), body)
        links = "".join(
            f'<li><a href="{_out_name(p)}">{html.escape(t)}</a></li>' for p, t in nav if p.parent == page.parent or p == INDEX
        )
        out.write_text(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)} - LoopForge</title>"
            "<style>body{font:16px/1.55 system-ui,sans-serif;max-width:60rem;margin:0 auto;padding:1rem}"
            "pre,code{background:#f4f4f5;border-radius:4px}pre{padding:.75rem;overflow:auto}code{padding:.1rem .3rem}"
            "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.3rem .5rem}"
            "nav{font-size:.9rem;border-bottom:1px solid #ddd;margin-bottom:1rem}@media(prefers-color-scheme:dark)"
            "{body{background:#111;color:#eee}pre,code{background:#222}a{color:#8ab4f8}td,th{border-color:#444}}</style>"
            f"<nav><a href=index.html>Home</a></nav>{body}<hr><details><summary>Pages in this section</summary><ul>{links}</ul></details>",
            encoding="utf-8",
        )
        count += 1
    return count


def _out_name(page: Path) -> str:
    if page == INDEX:
        return "index.html"
    rel = page.relative_to(ROOT)
    return ("_".join(rel.parts)).replace(".md", ".html")


def _fix_href(page: Path, m: re.Match[str]) -> str:
    target = (page.parent / (m.group(1) + ".md")).resolve()
    try:
        return f'href="{_out_name(target)}{m.group(2) or ""}"'
    except ValueError:
        return m.group(0)


def main() -> int:
    problems, graph = check()
    for p in problems:
        print(f"BROKEN: {p}")
    if problems:
        print(f"DOCS: FAIL ({len(problems)} problem(s) in {len(graph)} pages)")
        return 1
    if "--check" in sys.argv:
        print(f"DOCS: PASS ({len(graph)} pages, all internal links and anchors resolve)")
        return 0
    n = render()
    print(f"DOCS: PASS ({n} pages written to docs/_site/, all internal links and anchors resolve)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
