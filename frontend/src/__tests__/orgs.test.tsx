import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient, api } from "../api/client";
import type { OrgMembership, Role } from "../api/types";
import { AuthProvider, pickOrg } from "../auth";
import { Approvals } from "../components/Approvals";
import { Protected } from "../components/Layout";
import { Admin } from "../pages/Admin";
import { Login, parseSsoFragment } from "../pages/Login";

function mem() {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  };
}
const json = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const org = (id: string, role: Role, name = `Org ${id}`): OrgMembership => ({ id, name, slug: `slug-${id}`, role });

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});
afterEach(() => sessionStorage.clear());

describe("ApiClient organization header", () => {
  it("sends X-Org-Id on authenticated requests only, and forgets it on sign-out", async () => {
    const storage = mem();
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json(200, { access_token: "a", refresh_token: "r" }))
      .mockImplementation(() => Promise.resolve(json(200, {})));
    const c = new ApiClient({ fetchImpl, storage });
    await c.login("a@b.co", "pw");
    c.setOrg("org-1");
    await c.get("/tasks");
    await c.request("GET", "/auth/config", { auth: false });
    const headers = (i: number) => (fetchImpl.mock.calls[i][1] as RequestInit).headers as Record<string, string>;
    expect(headers(1)["X-Org-Id"]).toBe("org-1");
    expect(headers(2)["X-Org-Id"]).toBeUndefined(); // public routes get no organization
    c.clear();
    expect(c.orgId).toBeNull();
  });

  it("adopts tokens handed over by the SSO callback", async () => {
    const storage = mem();
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(() => Promise.resolve(json(200, { ok: 1 })));
    const c = new ApiClient({ fetchImpl, storage });
    c.adoptTokens({ access_token: "sso-a", refresh_token: "sso-r" });
    await c.get("/orgs");
    expect(storage.getItem("loopforge.refresh")).toBe("sso-r");
    expect(((fetchImpl.mock.calls[0][1] as RequestInit).headers as Record<string, string>).Authorization).toBe("Bearer sso-a");
  });
});

describe("pickOrg", () => {
  const list = [org("a", "admin"), org("b", "viewer")];
  it("keeps the remembered organization while the user still belongs to it", () => {
    expect(pickOrg(list, "b")?.id).toBe("b");
  });
  it("falls back to the first when it is unknown or gone", () => {
    expect(pickOrg(list, "gone")?.id).toBe("a");
    expect(pickOrg(list, null)?.id).toBe("a");
    expect(pickOrg([], "a")).toBeNull();
  });
});

function app(orgs: OrgMembership[], path = "/") {
  sessionStorage.setItem("loopforge.refresh", "r");
  vi.spyOn(api, "get").mockImplementation((p: string) => {
    if (p === "/auth/me") return Promise.resolve({ id: "u", email: "me@example.com" } as never);
    if (p === "/orgs") return Promise.resolve(orgs as never);
    return Promise.resolve([] as never);
  });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route element={<Protected />}>
            <Route path="/" element={<div>home page</div>} />
            <Route path="/admin" element={<Admin />} />
          </Route>
          <Route path="/login" element={<div>login page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("role-aware navigation", () => {
  it.each([
    ["viewer", false, false],
    ["developer", true, false],
    ["approver", true, false],
    ["admin", true, true],
  ] as [Role, boolean, boolean][])("%s sees New task=%s, Admin=%s", async (role, newTask, admin) => {
    app([org("o1", role)]);
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(!!screen.queryByRole("link", { name: "New task" })).toBe(newTask);
    expect(!!screen.queryByRole("link", { name: "Admin" })).toBe(admin);
    expect(screen.getByTestId("role")).toHaveTextContent(role);
  });

  it("the admin page refuses a non-admin who navigates to it directly", async () => {
    app([org("o1", "developer")], "/admin");
    expect(await screen.findByText(/for admins/)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Members" })).toBeNull();
  });

  it("switching organization changes the header, the role and remounts the page", async () => {
    app([org("o1", "admin", "Alpha"), org("o2", "viewer", "Beta")]);
    await screen.findByText("home page");
    expect(api.orgId).toBe("o1");
    expect(screen.getByRole("link", { name: "Admin" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Organization"), "o2");
    expect(api.orgId).toBe("o2");
    await waitFor(() => expect(screen.getByTestId("role")).toHaveTextContent("viewer"));
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    expect(screen.queryByRole("link", { name: "New task" })).toBeNull();
  });

  it("sends a signed-out visitor to the login page", async () => {
    sessionStorage.clear();
    render(
      <MemoryRouter>
        <AuthProvider>
          <Routes>
            <Route element={<Protected />}><Route path="/" element={<div>home page</div>} /></Route>
            <Route path="/login" element={<div>login page</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });
});

describe("approvals by role", () => {
  const pending = {
    id: "a1", kind: "plan", iteration_number: 1, status: "pending", summary: "Review the plan",
    detail: {}, created_at: "2026-01-01T00:00:00", decided_at: null,
  };
  it("hides the decision buttons from people who may not decide", async () => {
    vi.spyOn(api, "get").mockResolvedValue([pending]);
    render(<Approvals taskId="t" signal={0} canDecide={false} onDecided={() => undefined} />);
    expect(await screen.findByText(/waiting for an approver/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("single sign-on on the login page", () => {
  function renderLogin(ssoEnabled: boolean) {
    vi.spyOn(api, "request").mockResolvedValue({ sso_enabled: ssoEnabled } as never);
    vi.spyOn(api, "get").mockImplementation((p: string) =>
      Promise.resolve((p === "/auth/me" ? { id: "u", email: "s@x.co" } : [org("o1", "admin")]) as never),
    );
    return render(
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<div>home page</div>} />
            <Route path="/login" element={<Login />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  it("shows the SSO button only when the server has it configured", async () => {
    window.history.replaceState(null, "", "/login");
    sessionStorage.setItem("loopforge.refresh", "");
    sessionStorage.clear();
    const { unmount } = renderLogin(false);
    await waitFor(() => expect(api.request).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /SSO/ })).toBeNull();
    unmount();
    renderLogin(true);
    expect(await screen.findByRole("link", { name: "Sign in with SSO" })).toHaveAttribute("href", "/api/v1/auth/sso/login");
  });

  it("parses what the callback put in the fragment", () => {
    expect(parseSsoFragment("#access_token=a&refresh_token=r")).toEqual({ tokens: { access_token: "a", refresh_token: "r" } });
    expect(parseSsoFragment("#error=state%20mismatch")).toEqual({ error: "state mismatch" });
    expect(parseSsoFragment("")).toEqual({});
    expect(parseSsoFragment("#access_token=only")).toEqual({});
  });

  it("takes the tokens, removes them from the URL and signs in", async () => {
    window.history.replaceState(null, "", "/login#access_token=AAA&refresh_token=RRR");
    const adopt = vi.spyOn(api, "adoptTokens");
    renderLogin(true);
    expect(await screen.findByText("home page")).toBeInTheDocument();
    expect(adopt).toHaveBeenCalledWith({ access_token: "AAA", refresh_token: "RRR" });
    expect(window.location.hash).toBe(""); // tokens do not linger in the address bar or history
  });

  it("shows a failed SSO attempt's message", async () => {
    window.history.replaceState(null, "", "/login#error=this%20email%20domain%20is%20not%20allowed");
    renderLogin(true);
    expect(await screen.findByRole("alert")).toHaveTextContent("this email domain is not allowed");
    expect(window.location.hash).toBe("");
  });
});

describe("admin page", () => {
  function adminPage() {
    sessionStorage.setItem("loopforge.refresh", "r");
    const members = [
      { user_id: "u1", email: "boss@example.com", role: "admin" },
      { user_id: "u2", email: "dev@example.com", role: "developer" },
    ];
    vi.spyOn(api, "get").mockImplementation((p: string) => {
      if (p === "/auth/me") return Promise.resolve({ id: "u1", email: "boss@example.com" } as never);
      if (p === "/orgs") return Promise.resolve([org("o1", "admin", "Alpha")] as never);
      if (p.endsWith("/members")) return Promise.resolve(members as never);
      if (p.endsWith("/audit")) return Promise.resolve([] as never);
      if (p.endsWith("/usage")) {
        return Promise.resolve({ tokens_used: 10, token_quota_month: 100, tokens_remaining: 90, tasks_created: 1, max_tasks_month: null, tasks_remaining: null } as never);
      }
      return Promise.resolve({ id: "o1", name: "Alpha", slug: "slug-o1", token_quota_month: 100, max_tasks_month: null, retention_days: null, redact_pii: false } as never);
    });
    const request = vi.spyOn(api, "request").mockResolvedValue({} as never);
    const post = vi.spyOn(api, "post").mockResolvedValue({} as never);
    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <AuthProvider>
          <Routes>
            <Route element={<Protected />}><Route path="/admin" element={<Admin />} /></Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
    return { request, post };
  }

  it("changes a role, removes a member and adds one", async () => {
    const { request, post } = adminPage();
    const row = (await screen.findByRole("cell", { name: "dev@example.com" })).closest("tr")!;
    await userEvent.selectOptions(within(row).getByLabelText("Role of dev@example.com"), "viewer");
    expect(request).toHaveBeenCalledWith("PATCH", "/orgs/o1/members/u2", { json: { role: "viewer" } });
    await userEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(request).toHaveBeenCalledWith("DELETE", "/orgs/o1/members/u2");
    await userEvent.type(screen.getByLabelText(/Add an existing user/), "new@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));
    expect(post).toHaveBeenCalledWith("/orgs/o1/members", { email: "new@example.com", role: "developer" });
  });

  it("shows the server's refusal, e.g. removing the last admin", async () => {
    const { request } = adminPage();
    request.mockRejectedValueOnce(new Error("An organization needs at least one admin"));
    const row = (await screen.findByRole("cell", { name: "boss@example.com" })).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least one admin");
  });

  it("clears a cap when its box is emptied and saves the rest", async () => {
    const { request } = adminPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Usage & limits" }));
    const quota = await screen.findByLabelText("Monthly token quota");
    await waitFor(() => expect(quota).toHaveValue("100"));
    await userEvent.clear(quota);
    await userEvent.type(screen.getByLabelText("Keep finished tasks for (days)"), "30");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(request).toHaveBeenCalledWith("PATCH", "/orgs/o1", {
      json: { token_quota_month: null, max_tasks_month: null, retention_days: 30, redact_pii: false },
    });
  });

  it("only enables the delete button once the slug is typed exactly", async () => {
    const { request } = adminPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Data" }));
    const button = await screen.findByRole("button", { name: "Delete everything" });
    expect(button).toBeDisabled();
    const box = screen.getByLabelText("Confirm organization slug");
    await userEvent.type(box, "slug-o");
    expect(button).toBeDisabled();
    await userEvent.type(box, "1");
    await waitFor(() => expect(button).toBeEnabled());
    request.mockResolvedValueOnce({ deleted_tasks: 3 } as never);
    await userEvent.click(button);
    expect(request).toHaveBeenCalledWith("DELETE", "/orgs/o1/data", { json: { confirm: "slug-o1" } });
    expect(await screen.findByText("Deleted 3 task(s).")).toBeInTheDocument();
  });
});
