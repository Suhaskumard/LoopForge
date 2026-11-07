import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildTree, CodeView, DiffView, Kpi } from "../components/ui";
import { diffStats, parseUnifiedDiff } from "../lib/diff";
import { DASH, money, num, pct, score, seconds } from "../lib/format";

const DIFF = [
  "--- iter_1/app/routes.py",
  "+++ iter_2/app/routes.py",
  "@@ -3,4 +3,4 @@",
  " def update(employee_id):",
  "-    employee = get_one(employee_id + 1)",
  "+    employee = get_one(employee_id)",
  "     return employee",
  "",
].join("\n");

describe("unified diff", () => {
  it("parses kinds and tracks old/new line numbers", () => {
    const lines = parseUnifiedDiff(DIFF);
    expect(lines.map((l) => l.kind)).toEqual(["meta", "meta", "hunk", "ctx", "del", "add", "ctx"]);
    const del = lines.find((l) => l.kind === "del")!;
    const add = lines.find((l) => l.kind === "add")!;
    expect([del.oldNo, del.newNo]).toEqual([4, null]);
    expect([add.oldNo, add.newNo]).toEqual([null, 4]);
    expect(diffStats(lines)).toEqual({ added: 1, removed: 1 });
  });

  it("renders as text, never as HTML (generated code is untrusted)", () => {
    const evil = '@@ -1,1 +1,1 @@\n-x\n+<img src=x onerror="alert(1)"><script>alert(2)</script>\n';
    const { container } = render(<DiffView diff={evil} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
    render(<CodeView content={"<b>bold</b>"} />);
    expect(screen.getByTestId("code").querySelector("b")).toBeNull();
  });
});

describe("file tree", () => {
  it("nests paths, directories first", () => {
    const tree = buildTree(["requirements.txt", "app/main.py", "app/routes.py", "tests/test_x.py"]);
    expect(tree.map((n) => n.name)).toEqual(["app", "tests", "requirements.txt"]);
    expect(tree[0].children.map((n) => n.path)).toEqual(["app/main.py", "app/routes.py"]);
  });
});

describe("formatting", () => {
  it("never shows a fake zero for values that are not computable", () => {
    for (const f of [pct, num, seconds, money, score]) expect(f(null)).toBe(DASH);
    expect(pct(0)).toBe("0.0%");
    expect(pct(66.667)).toBe("66.7%");
    expect(seconds(0.25)).toBe("250 ms");
    expect(seconds(125)).toBe("2 m 5 s");
    expect(money(0.0004)).toBe("$0.00040");
    expect(score(0.9)).toBe("90");
  });

  it("renders a KPI card", () => {
    render(<Kpi label="Task success rate" value="100.0%" hint="1 of 1 finished" />);
    expect(screen.getByTestId("kpi-Task success rate")).toHaveTextContent("100.0%");
  });
});
