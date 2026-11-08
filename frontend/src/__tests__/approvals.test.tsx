import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { Approvals } from "../components/Approvals";
import { describe as describeEvent } from "../lib/events";

const pending = {
  id: "a1", kind: "large_repair", iteration_number: 2, status: "pending",
  summary: "Repair modifies 7 files (limit 5)", detail: { files: ["app/a.py", "app/b.py"] },
  created_at: "2026-01-01T00:00:00", decided_at: null,
};

beforeEach(() => vi.restoreAllMocks());

describe("approval banner", () => {
  it("shows nothing when nothing is pending", async () => {
    vi.spyOn(api, "get").mockResolvedValue([{ ...pending, status: "approved" }]);
    const { container } = render(<Approvals taskId="t" signal={0} onDecided={() => undefined} />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container.querySelector("[data-testid=approvals]")).toBeNull();
  });

  it("lists the files and posts the decision", async () => {
    vi.spyOn(api, "get").mockResolvedValue([pending]);
    const post = vi.spyOn(api, "post").mockResolvedValue(undefined);
    const done = vi.fn();
    render(<Approvals taskId="t" signal={0} onDecided={done} />);
    expect(await screen.findByText(/needs your decision/)).toBeInTheDocument();
    expect(screen.getByText("app/a.py")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Approve and continue/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tasks/t/approvals/a1/approve"));
    expect(done).toHaveBeenCalled();
  });

  it("rejecting posts to the reject endpoint", async () => {
    vi.spyOn(api, "get").mockResolvedValue([pending]);
    const post = vi.spyOn(api, "post").mockResolvedValue(undefined);
    render(<Approvals taskId="t" signal={0} onDecided={() => undefined} />);
    await userEvent.click(await screen.findByRole("button", { name: /Reject/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/tasks/t/approvals/a1/reject"));
  });

  it("shows the server's error instead of failing silently", async () => {
    vi.spyOn(api, "get").mockResolvedValue([pending]);
    vi.spyOn(api, "post").mockRejectedValue(new Error("nothing is waiting for a decision"));
    render(<Approvals taskId="t" signal={0} onDecided={() => undefined} />);
    await userEvent.click(await screen.findByRole("button", { name: /Approve/ }));
    expect(await screen.findByText(/nothing is waiting/)).toBeInTheDocument();
  });
});

describe("approval events in the timeline", () => {
  it("describes requests and decisions", () => {
    const base = { id: "1", task_id: "t", timestamp: "" };
    expect(describeEvent({ ...base, event: "approval_requested", kind: "plan" })).toContain("plan");
    expect(describeEvent({ ...base, event: "approval_decided", kind: "plan", decision: "approved" })).toContain("approved");
  });
});
