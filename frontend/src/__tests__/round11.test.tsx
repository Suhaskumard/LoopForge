import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Task } from "../api/types";
import { AuthProvider } from "../auth";
import { CommandPalette, rememberTask, recentIds, taskActions } from "../components/CommandPalette";
import { QrImage } from "../components/Mfa";
import { daysInMonth, exceedDate, fillDays, projectMonth, type UsageRow } from "../components/Spend";
import { fuzzy, rank } from "../lib/fuzzy";

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

const row = (key: string, cost: number, tokens: number): UsageRow => ({
  key, label: key, tasks: 1, agent_runs: 1, tokens, estimated_cost_usd: cost, agent_seconds: 1,
});

describe("spend projection", () => {
  const today = new Date(Date.UTC(2026, 10, 10, 15)); // 10 Nov 2026, 30-day month

  it("fills missing days with zeros", () => {
    const days = fillDays([row("2026-11-02", 1, 100)], "2026-11-01", "2026-11-03");
    expect(days).toEqual([
      { day: "2026-11-01", cost: 0, tokens: 0 },
      { day: "2026-11-02", cost: 1, tokens: 100 },
      { day: "2026-11-03", cost: 0, tokens: 0 },
    ]);
    expect(daysInMonth(today)).toBe(30);
  });

  it("projects the month end from the run-rate, with a band from the last 7 days", () => {
    const days = fillDays([row("2026-11-01", 2, 2000), row("2026-11-10", 3, 3000)], "2026-11-01", "2026-11-10");
    const p = projectMonth(days, today);
    expect(p.spent).toBe(5);
    expect(p.dailyCost).toBeCloseTo(0.5);
    expect(p.daysLeft).toBe(20);
    expect(p.projectedCost).toBeCloseTo(15);
    expect(p.projectedTokens).toBe(15000);
    expect(p.low).toBe(5); // quietest of the last 7 days was 0
    expect(p.high).toBe(65); // busiest was 3 a day
  });

  it("predicts when the token quota runs out, only within this month", () => {
    expect(exceedDate(5000, 10000, 1000, today)).toBe("2026-11-15");
    expect(exceedDate(5000, 10000, 100, today)).toBeNull(); // 50 days away: not this month
    expect(exceedDate(5000, null, 1000, today)).toBeNull();
    expect(exceedDate(12000, 10000, 1000, today)).toBe("2026-11-10"); // already over
  });
});

describe("fuzzy search", () => {
  it("matches subsequences, prefers substrings and word starts", () => {
    expect(fuzzy("rrn", "Re-run as a regression check")?.indices).toEqual([0, 3, 5]);
    expect(fuzzy("xyz", "Re-run")).toBeNull();
    const ranked = rank("rep", ["Repair notes", "Open final report", "Prepare"], (s) => s).map((r) => r.item);
    expect(ranked[0]).toBe("Repair notes");
    expect(ranked).toContain("Open final report");
  });
});

describe("action palette", () => {
  const task = (over: Partial<Task>) =>
    ({ id: "11111111-1111-1111-1111-111111111111", requirement: "Build URL shortener", status: "COMPLETED", ...over }) as Task;

  it("offers only the actions that fit the task's status and the user's role", () => {
    expect(taskActions({ status: "COMPLETED" }, true)).toEqual(
      expect.arrayContaining(["rerun", "watch-daily", "watch-weekly", "continue", "ab"]),
    );
    expect(taskActions({ status: "FAILED" }, true)).toContain("retry");
    expect(taskActions({ status: "TESTING" }, true)).toContain("cancel");
    expect(taskActions({ status: "COMPLETED" }, false)).toEqual(["open", "code", "report", "graph", "copy"]);
  });

  it("remembers recent tasks, newest first, at most five", () => {
    for (const id of ["a", "b", "c", "d", "e", "f", "b"]) rememberTask(id);
    expect(recentIds()).toEqual(["b", "f", "e", "d", "c"]);
  });

  it("Tab opens a task's actions; without a role only read-only actions are offered", async () => {
    vi.spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/tasks") return [task({})] as never;
      throw new Error("not signed in");
    });
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    const onClose = vi.fn();
    render(
      <MemoryRouter>
        <AuthProvider>
          <CommandPalette open onClose={onClose} />
        </AuthProvider>
      </MemoryRouter>,
    );
    const box = screen.getByLabelText("Search pages and tasks");
    await userEvent.type(box, "url short");
    // matched characters are highlighted in separate spans, so look the row up by its accessible name
    expect(await screen.findByRole("button", { name: /Build URL shortener/ })).toBeInTheDocument();
    await userEvent.keyboard("{Tab}");
    // the auth context has no user in this test, so only the read-only actions are offered
    const actions = await screen.findByLabelText("Search actions");
    await userEvent.type(actions, "copy");
    expect(screen.getByRole("button", { name: /Copy link/ })).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
  });

  it("> limits the list to commands", async () => {
    vi.spyOn(api, "get").mockResolvedValue([] as never);
    render(
      <MemoryRouter>
        <AuthProvider>
          <CommandPalette open onClose={() => {}} onToggleTheme={() => {}} onShortcuts={() => {}} />
        </AuthProvider>
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText("Search pages and tasks"), ">theme");
    await waitFor(() => expect(screen.getByRole("button", { name: /Toggle light \/ dark theme/ })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Task Graph/ })).toBeNull();
  });
});

describe("two-factor QR", () => {
  it("draws an SVG QR code for the setup link", () => {
    render(<QrImage text="otpauth://totp/LoopForge:a@b.c?secret=JBSWY3DPEHPK3PXP&issuer=LoopForge" />);
    const svg = screen.getByTestId("mfa-qr");
    expect(svg.getAttribute("viewBox")).toBe("0 0 45 45"); // version 4 (33 modules) + 2×4 quiet zone
    expect(svg.querySelector("path")?.getAttribute("d")?.length).toBeGreaterThan(100);
  });
});
