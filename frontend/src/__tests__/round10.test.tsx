import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiClient, MfaRequired } from "../api/client";
import type { Task } from "../api/types";
import { AuthProvider } from "../auth";
import { groupSecret, TwoFactorCard } from "../components/Mfa";
import { actionsFor, explore, TaskExplorer } from "../components/TaskExplorer";
import { parseUnifiedDiff } from "../lib/diff";
import { compareListings, unifiedDiff } from "../lib/linediff";
import { Login } from "../pages/Login";

beforeEach(() => vi.restoreAllMocks());

const task = (over: Partial<Task>): Task =>
  ({
    id: "t", project_id: "p", requirement: "r", status: "COMPLETED", max_iterations: 5, current_iteration: 1,
    acceptance_criteria: [], token_budget: null, max_cost: null, require_plan_approval: false, source_type: "none",
    source_ref: null, source_hash: null, version: 1, created_at: "2026-11-01T00:00:00", ...over,
  }) as Task;

describe("two-factor sign-in", () => {
  it("the client turns 401 + X-MFA-Required into MfaRequired and sends the code", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ error: { code: "http_401", message: "MFA code required" } }), {
          status: 401,
          headers: { "X-MFA-Required": "true" },
        }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "a", refresh_token: "r" }), { status: 200 }));
    const c = new ApiClient({ fetchImpl, storage: { getItem: () => null, setItem: () => {}, removeItem: () => {} } });
    await expect(c.login("a@b.c", "pw")).rejects.toBeInstanceOf(MfaRequired);
    await c.login("a@b.c", "pw", "123 456");
    const body = fetchImpl.mock.calls[1][1].body as URLSearchParams;
    expect(body.get("mfa_code")).toBe("123456");
  });

  it("the login page asks for the code instead of showing an error", async () => {
    vi.spyOn(api, "request").mockResolvedValue({ sso_enabled: false });
    const login = vi.spyOn(api, "login").mockRejectedValueOnce(new MfaRequired()).mockRejectedValueOnce(new Error("Invalid MFA code"));
    render(<MemoryRouter><AuthProvider><Login /></AuthProvider></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Email"), "a@b.c");
    await userEvent.type(screen.getByLabelText("Password"), "pw123456");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const code = await screen.findByLabelText("Authentication code");
    expect(screen.queryByRole("alert")).toBeNull();
    await userEvent.type(code, "000000");
    await userEvent.click(screen.getByRole("button", { name: "Verify and sign in" }));
    expect(login).toHaveBeenLastCalledWith("a@b.c", "pw123456", "000000");
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid MFA code");
  });

  it("settings: set up, confirm a code, recovery codes shown once", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ enabled: false, recovery_codes_left: 0 });
    const post = vi.spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path === "/auth/mfa/enroll") return { secret: "ABCDEFGHIJKLMNOP", otpauth_uri: "otpauth://totp/x" } as never;
      return { recovery_codes: ["r1-aaaa", "r2-bbbb"] } as never;
    });
    render(<TwoFactorCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Set up" }));
    expect(await screen.findByTestId("mfa-secret")).toHaveTextContent("ABCD EFGH IJKL MNOP");
    get.mockResolvedValue({ enabled: true, recovery_codes_left: 2 });
    await userEvent.type(screen.getByLabelText("Code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(post).toHaveBeenLastCalledWith("/auth/mfa/activate", { code: "123456" });
    expect(await screen.findByTestId("one-time-secret")).toHaveTextContent("r1-aaaa");
    expect(await screen.findByTestId("mfa-state")).toHaveTextContent("On");
    expect(groupSecret("ABCDEFGH")).toBe("ABCD EFGH");
  });
});

describe("task explorer", () => {
  const tasks = [
    task({ id: "a", requirement: "Build URL shortener", status: "COMPLETED", current_iteration: 2, created_at: "2026-11-01T00:00:00" }),
    task({ id: "b", requirement: "Todo API", status: "FAILED", current_iteration: 5, created_at: "2026-11-03T00:00:00" }),
    task({ id: "c", requirement: "CSV stats", status: "TESTING", current_iteration: 1, created_at: "2026-11-02T00:00:00" }),
  ];

  it("filters, searches and sorts", () => {
    expect(explore(tasks, "", "", "newest").map((t) => t.id)).toEqual(["b", "c", "a"]);
    expect(explore(tasks, "", "", "oldest").map((t) => t.id)).toEqual(["a", "c", "b"]);
    expect(explore(tasks, "", "", "iterations").map((t) => t.id)).toEqual(["b", "a", "c"]);
    expect(explore(tasks, "url", "", "newest").map((t) => t.id)).toEqual(["a"]);
    expect(explore(tasks, "", "needs", "newest").map((t) => t.id)).toEqual(["b"]);
    expect(explore(tasks, "", "running", "newest").map((t) => t.id)).toEqual(["c"]);
    expect(tasks.map(actionsFor)).toEqual([["rerun"], ["retry"], ["cancel"]]);
  });

  it("bulk retry calls retry then start for each selected task", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({});
    const changed = vi.fn();
    render(<MemoryRouter><TaskExplorer tasks={tasks} canAct onChanged={changed} /></MemoryRouter>);
    await userEvent.click(screen.getByLabelText("Select Todo API"));
    await userEvent.click(screen.getByRole("button", { name: "Retry (1)" }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(post.mock.calls.map((c) => c[0])).toEqual(["/tasks/b/retry", "/tasks/b/start"]);
  });
});

describe("A/B code diff", () => {
  it("produces a unified diff the existing DiffView can parse", () => {
    const d = unifiedDiff("a\nb\nc\nd", "a\nB\nc\nd\ne", "A/x", "B/x");
    const lines = parseUnifiedDiff(d);
    expect(lines.filter((l) => l.kind === "del").map((l) => l.text)).toEqual(["b"]);
    expect(lines.filter((l) => l.kind === "add").map((l) => l.text)).toEqual(["B", "e"]);
    expect(lines.find((l) => l.kind === "add" && l.text === "e")?.newNo).toBe(5);
    expect(unifiedDiff("same", "same")).toBe("");
  });

  it("compares listings by hash, changed files first", () => {
    const r = compareListings(
      [{ path: "x.py", sha256: "1" }, { path: "same.py", sha256: "s" }, { path: "gone.py", sha256: "g" }],
      [{ path: "x.py", sha256: "2" }, { path: "same.py", sha256: "s" }, { path: "new.py", sha256: "n" }],
    );
    expect(r).toEqual([
      { path: "x.py", change: "changed" },
      { path: "gone.py", change: "only-a" },
      { path: "new.py", change: "only-b" },
      { path: "same.py", change: "same" },
    ]);
  });
});
