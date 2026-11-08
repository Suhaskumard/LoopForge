import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { ReviewComments } from "../components/Approvals";
import { AccountBanners, NotificationBell } from "../components/Notifications";
import { Onboarding } from "../components/Onboarding";
import { ForgotPassword, ResetPassword, VerifyEmail } from "../pages/AccountLinks";
import { Invites, MemberQuotas } from "../pages/Admin";
import { CreateTask } from "../pages/CreateTask";
import { Sessions } from "../pages/Settings";

beforeEach(() => vi.restoreAllMocks());

const at = (url: string, ui: React.ReactElement, path = "/x") =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path={path} element={ui} />
        <Route path="*" element={<p>elsewhere</p>} />
      </Routes>
    </MemoryRouter>,
  );

describe("email links", () => {
  it("verifies once and says so", async () => {
    const req = vi.spyOn(api, "request").mockResolvedValue({});
    at("/x?token=abc123abc123", <VerifyEmail />);
    expect(await screen.findByText(/address is verified/)).toBeInTheDocument();
    expect(req).toHaveBeenCalledWith("POST", "/auth/verify-email", { json: { token: "abc123abc123" }, auth: false });
  });

  it("shows a neutral error for a bad or missing link", async () => {
    vi.spyOn(api, "request").mockRejectedValue(new Error("nope"));
    at("/x?token=bad", <VerifyEmail />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid or has expired/);
  });

  it("the forgot-password page gives the same answer for any address", async () => {
    const req = vi.spyOn(api, "request").mockResolvedValue({});
    at("/x", <ForgotPassword />);
    await userEvent.type(screen.getByLabelText("Email"), "ghost@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByText(/If that address is registered/)).toBeInTheDocument();
    expect(req).toHaveBeenCalledWith("POST", "/auth/password-reset/request", {
      json: { email: "ghost@example.com" },
      auth: false,
    });
  });

  it("reset needs the token and posts the new password", async () => {
    const req = vi.spyOn(api, "request").mockResolvedValue(undefined);
    at("/x?token=tok-tok-tok-1", <ResetPassword />);
    await userEvent.type(screen.getByLabelText("New password"), "newpass123");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() =>
      expect(req).toHaveBeenCalledWith("POST", "/auth/password-reset/confirm", {
        json: { token: "tok-tok-tok-1", password: "newpass123" },
        auth: false,
      }),
    );
    expect(await screen.findByText(/Password changed/)).toBeInTheDocument();
  });

  it("reset without a token cannot be submitted", () => {
    at("/x", <ResetPassword />);
    expect(screen.getByRole("button", { name: "Change password" })).toBeDisabled();
  });
});

describe("notifications and banners", () => {
  const note = (over = {}) => ({
    id: "n1", kind: "task.completed", title: "Task finished: x", detail: { task_id: "t1" },
    read_at: null, created_at: "2026-01-01T00:00:00", ...over,
  });

  it("shows the unread count and marks one read when clicked", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ unread: 1, items: [note()] });
    const post = vi.spyOn(api, "post").mockResolvedValue(undefined);
    at("/x", <NotificationBell />);
    expect(await screen.findByTestId("unread")).toHaveTextContent("1");
    await userEvent.click(screen.getByRole("button", { name: /Notifications, 1 unread/ }));
    await userEvent.click(await screen.findByRole("link", { name: "Task finished: x" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/notifications/n1/read"));
    expect(get).toHaveBeenCalled();
  });

  it("asks an unverified user to verify and can resend", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ org: {}, member: {}, warnings: [] });
    const post = vi.spyOn(api, "post").mockResolvedValue(undefined);
    render(<AccountBanners user={{ id: "u", email: "me@example.com", email_verified_at: null }} orgId="o" />);
    expect(screen.getByTestId("verify-banner")).toHaveTextContent("me@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send it again" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/auth/resend-verification"));
    expect(await screen.findByText(/Sent/)).toBeInTheDocument();
  });

  it("shows nothing for a verified user with no quota warnings, and warns near a cap", async () => {
    const warnings = [{ scope: "member", resource: "tasks", used: 8, cap: 10 }];
    vi.spyOn(api, "get").mockResolvedValue({ org: {}, member: {}, warnings });
    render(<AccountBanners user={{ id: "u", email: "a@b.c", email_verified_at: "2026-01-01T00:00:00" }} orgId="o" />);
    expect(await screen.findByTestId("quota-banner")).toHaveTextContent("You have used 8 of 10 tasks");
    expect(screen.queryByTestId("verify-banner")).toBeNull();
  });
});

describe("guided experience", () => {
  it("the onboarding card lists what is left and hides itself when complete", async () => {
    const steps = [
      { id: "a", title: "Verify your email", done: true, hint: "h1" },
      { id: "b", title: "Create your first task", done: false, hint: "Pick a template" },
    ];
    vi.spyOn(api, "get").mockResolvedValue({ steps, complete: false });
    const { unmount } = at("/x", <Onboarding />);
    expect(await screen.findByText("Getting started (1/2)")).toBeInTheDocument();
    expect(screen.getByText(/Pick a template/)).toBeInTheDocument();
    unmount();
    vi.spyOn(api, "get").mockResolvedValue({ steps, complete: true });
    const { container } = at("/x", <Onboarding />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container.querySelector("[data-testid=onboarding]")).toBeNull();
  });

  it("choosing a template fills the form", async () => {
    vi.spyOn(api, "get").mockResolvedValue([
      {
        id: "crud-api", name: "CRUD REST API", description: "d", language: "python",
        requirement: "Build CRUD.", acceptance_criteria: ["a", "b"],
      },
    ]);
    at("/x", <CreateTask />);
    await userEvent.selectOptions(await screen.findByLabelText("Template"), "crud-api");
    expect(screen.getByLabelText("Natural-language requirement")).toHaveValue("Build CRUD.");
    expect(screen.getByLabelText(/Project name/)).toHaveValue("crud_api");
  });

  it("review comments list existing ones and post a new one", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue([
      { id: "c1", author: "rev@example.com", file_path: "app/x.py", line: 3, body: "Why this?", created_at: "x" },
    ]);
    const post = vi.spyOn(api, "post").mockResolvedValue({});
    at("/x", <ReviewComments taskId="t" approvalId="a" canComment />);
    expect(await screen.findByText(/Why this\?/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Comment"), "Looks fine");
    await userEvent.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/tasks/t/approvals/a/comments", { file_path: "", line: null, body: "Looks fine" }),
    );
    expect(get.mock.calls.length).toBeGreaterThan(1); // reloaded after posting
  });

  it("viewers see comments but no form", async () => {
    vi.spyOn(api, "get").mockResolvedValue([]);
    at("/x", <ReviewComments taskId="t" approvalId="a" canComment={false} />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Add comment" })).toBeNull();
  });
});

describe("sessions and admin additions", () => {
  it("lists sessions, hides sign-out for the current one and revokes another", async () => {
    vi.spyOn(api, "request").mockResolvedValue([
      { family_id: "f1", user_agent: "Firefox", ip: "1.1.1.1", created_at: "2026-01-01T00:00:00", last_used_at: null, current: true },
      { family_id: "f2", user_agent: "Safari", ip: "2.2.2.2", created_at: "2026-01-01T00:00:00", last_used_at: null, current: false },
    ]);
    const del = vi.spyOn(api, "delete").mockResolvedValue(undefined);
    at("/x", <Sessions />);
    expect(await screen.findByText("this session")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Sign out" })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/auth/sessions/f2"));
  });

  it("admins invite by email and see a neutral confirmation", async () => {
    vi.spyOn(api, "get").mockResolvedValue([]);
    const post = vi.spyOn(api, "post").mockResolvedValue({});
    at("/x", <Invites orgId="o1" />);
    await userEvent.type(screen.getByLabelText("Email to invite"), "new@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/orgs/o1/invites", { email: "new@example.com", role: "developer" }));
    expect(await screen.findByText(/If the address can receive an invitation/)).toBeInTheDocument();
  });

  it("saves a member quota, with empty boxes meaning no cap", async () => {
    vi.spyOn(api, "get").mockResolvedValue([{ user_id: "u1", email: "dev@example.com", role: "developer" }]);
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    at("/x", <MemberQuotas orgId="o1" />);
    await userEvent.type(await screen.findByLabelText("Task limit for dev@example.com"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Save limits for dev@example.com" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/orgs/o1/members/u1/quota", { token_quota_month: null, max_tasks_month: 3 }),
    );
  });
});
