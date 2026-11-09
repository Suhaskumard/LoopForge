import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LiveEvent } from "../api/types";
import { ago, clock, elapsedSeconds, glyph, groupByIteration, StageRail } from "../components/LiveViz";
import { initialLive, reduceEvent } from "../lib/events";

const ev = (id: string, event: string, extra: Partial<LiveEvent> = {}): LiveEvent => ({
  id, event, task_id: "t", timestamp: `2026-11-09T10:00:${id.padStart(2, "0")}Z`, ...extra,
});

describe("live workflow helpers", () => {
  afterEach(() => vi.restoreAllMocks());

  it("measures elapsed time, frozen once the loop ends", () => {
    const tl = [ev("1", "task_started"), ev("31", "agent_started", { agent: "Planner" })];
    expect(elapsedSeconds(tl, "COMPLETED")).toBe(30);
    expect(elapsedSeconds(tl, null, Date.parse("2026-11-09T10:01:01Z"))).toBe(60);
    expect(elapsedSeconds([], null)).toBe(0);
    expect(clock(75)).toBe("01:15");
  });

  it("groups events by iteration and labels them", () => {
    const tl = [
      ev("1", "task_started"),
      ev("2", "agent_started", { agent: "Planner", iteration: 1 }),
      ev("3", "agent_completed", { agent: "Planner", iteration: 1, status: "success" }),
      ev("4", "retry_scheduled"),
      ev("5", "agent_started", { agent: "Repair", iteration: 2 }),
    ];
    const groups = groupByIteration(tl);
    expect(groups.map((g) => [g.iteration, g.events.length])).toEqual([[1, 4], [2, 1]]);
    expect(glyph(tl[2])).toBe("✓");
    expect(glyph(tl[3])).toBe("↺");
    expect(ago("2026-11-09T10:00:00Z", Date.parse("2026-11-09T10:02:30Z"))).toBe("2m ago");
  });

  it("the stage rail marks finished, running and retry states", () => {
    let live = initialLive();
    for (const e of [
      ev("1", "agent_started", { agent: "Planner", iteration: 1 }),
      ev("2", "agent_completed", { agent: "Planner", iteration: 1, status: "success" }),
      ev("3", "agent_started", { agent: "Builder", iteration: 1 }),
      ev("4", "retry_scheduled"),
    ]) live = reduceEvent(live, e);
    const { container } = render(<StageRail live={live} />);
    expect(container.querySelector(".stage.success .stage-label")?.textContent).toBe("Plan");
    expect(container.querySelector(".stage.running .stage-label")?.textContent).toBe("Build");
    expect(screen.getByText(/Repair loop · 1 retry/)).toBeInTheDocument();
  });
});
