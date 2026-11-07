/**
 * Typed API client with single-flight token refresh.
 *
 * Storage choice (ADR-0011): the short-lived access token lives only in memory; the rotating
 * refresh token lives in sessionStorage so a reload keeps the session but closing the tab
 * ends it. Refresh tokens rotate on every use and replay revokes the family (ADR-0006).
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

interface Tokens {
  access_token: string;
  refresh_token: string;
}

export interface ClientOptions {
  fetchImpl?: typeof fetch;
  storage?: Pick<Storage, "getItem" | "setItem" | "removeItem">;
  base?: string;
  onAuthLost?: () => void;
}

const REFRESH_KEY = "loopforge.refresh";

export class ApiClient {
  private access: string | null = null;
  private refreshing: Promise<boolean> | null = null;
  private readonly fetchImpl: typeof fetch;
  private readonly storage: NonNullable<ClientOptions["storage"]>;
  private readonly base: string;
  onAuthLost: () => void;

  constructor(opts: ClientOptions = {}) {
    this.fetchImpl = opts.fetchImpl ?? ((...a) => fetch(...a));
    this.storage = opts.storage ?? safeStorage();
    this.base = opts.base ?? "/api/v1";
    this.onAuthLost = opts.onAuthLost ?? (() => undefined);
  }

  get hasSession(): boolean {
    return this.access !== null || this.storage.getItem(REFRESH_KEY) !== null;
  }

  private setTokens(t: Tokens): void {
    this.access = t.access_token;
    this.storage.setItem(REFRESH_KEY, t.refresh_token);
  }

  clear(): void {
    this.access = null;
    this.storage.removeItem(REFRESH_KEY);
  }

  async login(email: string, password: string): Promise<void> {
    const body = new URLSearchParams({ username: email, password });
    const res = await this.fetchImpl(`${this.base}/auth/login`, { method: "POST", body });
    if (!res.ok) throw await toError(res);
    this.setTokens((await res.json()) as Tokens);
  }

  async register(email: string, password: string): Promise<void> {
    await this.request("POST", "/auth/register", { json: { email, password }, auth: false });
  }

  async logout(): Promise<void> {
    const refresh = this.storage.getItem(REFRESH_KEY);
    if (refresh) {
      await this.fetchImpl(`${this.base}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      }).catch(() => undefined);
    }
    this.clear();
  }

  /** One refresh at a time: concurrent 401s all wait for the same rotation. */
  refresh(): Promise<boolean> {
    if (this.refreshing) return this.refreshing;
    const token = this.storage.getItem(REFRESH_KEY);
    if (!token) return Promise.resolve(false);
    this.refreshing = (async () => {
      try {
        const res = await this.fetchImpl(`${this.base}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: token }),
        });
        if (!res.ok) {
          this.clear();
          return false;
        }
        this.setTokens((await res.json()) as Tokens);
        return true;
      } catch {
        return false; // network trouble is not a reason to log the user out
      } finally {
        this.refreshing = null;
      }
    })();
    return this.refreshing;
  }

  /** A valid access token for WebSocket URLs (browsers cannot set headers on a socket). */
  async accessToken(): Promise<string | null> {
    if (this.access === null && !(await this.refresh())) return null;
    return this.access;
  }

  async request<T>(
    method: string,
    path: string,
    opts: { json?: unknown; auth?: boolean; query?: Record<string, string | number | undefined> } = {},
  ): Promise<T> {
    const send = async (): Promise<Response> => {
      const headers: Record<string, string> = {};
      if (opts.json !== undefined) headers["Content-Type"] = "application/json";
      if (opts.auth !== false && this.access) headers["Authorization"] = `Bearer ${this.access}`;
      return this.fetchImpl(this.base + path + queryString(opts.query), {
        method,
        headers,
        body: opts.json !== undefined ? JSON.stringify(opts.json) : undefined,
      });
    };
    if (opts.auth !== false && this.access === null) await this.refresh();
    let res = await send();
    if (res.status === 401 && opts.auth !== false) {
      if (await this.refresh()) res = await send();
      if (res.status === 401) {
        this.clear();
        this.onAuthLost();
      }
    }
    if (!res.ok) throw await toError(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  get<T>(path: string, query?: Record<string, string | number | undefined>): Promise<T> {
    return this.request<T>("GET", path, { query });
  }
  post<T>(path: string, json?: unknown): Promise<T> {
    return this.request<T>("POST", path, { json });
  }

  /** Authenticated binary download (artifact zip). */
  async blob(path: string): Promise<Blob> {
    if (this.access === null) await this.refresh();
    const res = await this.fetchImpl(this.base + path, {
      headers: this.access ? { Authorization: `Bearer ${this.access}` } : {},
    });
    if (!res.ok) throw await toError(res);
    return res.blob();
  }
}

function queryString(q?: Record<string, string | number | undefined>): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code: string; message: string; details?: unknown } };
    if (body.error) return new ApiError(res.status, body.error.code, body.error.message, body.error.details);
  } catch {
    /* fall through */
  }
  return new ApiError(res.status, "http_error", res.statusText || `HTTP ${res.status}`);
}

function safeStorage(): NonNullable<ClientOptions["storage"]> {
  try {
    return window.sessionStorage;
  } catch {
    const mem = new Map<string, string>();
    return {
      getItem: (k) => mem.get(k) ?? null,
      setItem: (k, v) => void mem.set(k, v),
      removeItem: (k) => void mem.delete(k),
    };
  }
}

export const api = new ApiClient();
