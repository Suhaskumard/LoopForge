import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "../api/client";

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

describe("ApiClient", () => {
  it("logs in, stores the refresh token and sends the bearer token", async () => {
    const storage = mem();
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json(200, { access_token: "a1", refresh_token: "r1" }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    const c = new ApiClient({ fetchImpl, storage });
    await c.login("a@b.co", "pw");
    expect(storage.getItem("loopforge.refresh")).toBe("r1");
    await c.get("/tasks");
    const init = fetchImpl.mock.calls[1][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer a1");
  });

  it("refreshes once on 401 and retries the request", async () => {
    const storage = mem();
    storage.setItem("loopforge.refresh", "r1");
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json(200, { access_token: "a1", refresh_token: "r2" })) // no access token yet
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "expired" } }))
      .mockResolvedValueOnce(json(200, { access_token: "a2", refresh_token: "r3" }))
      .mockResolvedValueOnce(json(200, { value: 1 }));
    const c = new ApiClient({ fetchImpl, storage });
    expect(await c.get("/x")).toEqual({ value: 1 });
    expect(storage.getItem("loopforge.refresh")).toBe("r3");
  });

  it("shares a single refresh between concurrent callers (token rotation safety)", async () => {
    const storage = mem();
    storage.setItem("loopforge.refresh", "r1");
    let refreshCalls = 0;
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async (url) => {
      if (String(url).endsWith("/auth/refresh")) {
        refreshCalls += 1;
        await new Promise((r) => setTimeout(r, 10));
        return json(200, { access_token: "a", refresh_token: `r${refreshCalls + 1}` });
      }
      return json(200, {});
    });
    const c = new ApiClient({ fetchImpl, storage });
    await Promise.all([c.get("/a"), c.get("/b"), c.get("/c")]);
    expect(refreshCalls).toBe(1);
  });

  it("clears the session and signals when refresh fails", async () => {
    const storage = mem();
    storage.setItem("loopforge.refresh", "dead");
    const lost = vi.fn();
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockImplementation(async () => json(401, { error: { code: "unauthorized", message: "no" } }));
    const c = new ApiClient({ fetchImpl, storage, onAuthLost: lost });
    await expect(c.get("/x")).rejects.toBeInstanceOf(ApiError);
    expect(storage.getItem("loopforge.refresh")).toBeNull();
    expect(lost).toHaveBeenCalled();
  });

  it("surfaces the server's error envelope", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(json(409, { error: { code: "conflict", message: "not PENDING" } }));
    const c = new ApiClient({ fetchImpl, storage: mem() });
    await expect(c.request("POST", "/tasks/1/start", { auth: false })).rejects.toMatchObject({
      status: 409,
      code: "conflict",
      message: "not PENDING",
    });
  });

  it("does not log the user out on a network error during refresh", async () => {
    const storage = mem();
    storage.setItem("loopforge.refresh", "r1");
    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline"));
    const c = new ApiClient({ fetchImpl, storage });
    expect(await c.refresh()).toBe(false);
    expect(storage.getItem("loopforge.refresh")).toBe("r1");
  });
});
