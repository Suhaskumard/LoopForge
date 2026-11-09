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

/** Sign-in needs the 6-digit code (or a recovery code) from the user's authenticator app. */
export class MfaRequired extends ApiError {
  constructor(message = "Enter the code from your authenticator app") {
    super(401, "mfa_required", message);
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
const ORG_KEY = "loopforge.org";

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

  /** Take over a session created elsewhere (the SSO callback hands tokens over in the URL fragment). */
  adoptTokens(t: Tokens): void {
    this.setTokens(t);
  }

  /** The organization every request is made in (`X-Org-Id`); remembered for the tab. */
  get orgId(): string | null {
    return this.storage.getItem(ORG_KEY);
  }
  setOrg(id: string | null): void {
    if (id) this.storage.setItem(ORG_KEY, id);
    else this.storage.removeItem(ORG_KEY);
  }
  private orgHeader(): Record<string, string> {
    const id = this.orgId;
    return id ? { "X-Org-Id": id } : {};
  }

  clear(): void {
    this.access = null;
    this.storage.removeItem(REFRESH_KEY);
    this.storage.removeItem(ORG_KEY);
  }

  async login(email: string, password: string, mfaCode?: string): Promise<void> {
    const body = new URLSearchParams({ username: email, password });
    if (mfaCode) body.set("mfa_code", mfaCode.replace(/\s+/g, ""));
    const res = await this.fetchImpl(`${this.base}/auth/login`, { method: "POST", body });
    if (!res.ok) {
      const err = await toError(res);
      // the password was right but the account has two-factor sign-in: ask for the code
      if (res.status === 401 && res.headers.get("X-MFA-Required") === "true") throw new MfaRequired(err.message);
      throw err;
    }
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
    opts: {
      json?: unknown;
      auth?: boolean;
      query?: Record<string, string | number | undefined>;
      headers?: Record<string, string>;
    } = {},
  ): Promise<T> {
    const send = async (): Promise<Response> => {
      const headers: Record<string, string> = opts.auth !== false ? this.orgHeader() : {};
      if (opts.json !== undefined) headers["Content-Type"] = "application/json";
      Object.assign(headers, opts.headers);
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
  put<T>(path: string, json?: unknown): Promise<T> {
    return this.request<T>("PUT", path, { json });
  }
  delete(path: string): Promise<void> {
    return this.request<void>("DELETE", path);
  }

  /** Sent as `X-Refresh-Token` so the sessions page can mark which session is this one. */
  get currentRefreshToken(): string | null {
    return this.storage.getItem(REFRESH_KEY);
  }

  /** Authenticated multipart upload (repository zip). The browser sets the multipart boundary. */
  async upload<T>(path: string, file: File): Promise<T> {
    const send = (): Promise<Response> => {
      const form = new FormData();
      form.append("file", file);
      return this.fetchImpl(this.base + path, {
        method: "POST",
        headers: { ...this.orgHeader(), ...(this.access ? { Authorization: `Bearer ${this.access}` } : {}) },
        body: form,
      });
    };
    if (this.access === null) await this.refresh();
    let res = await send();
    if (res.status === 401 && (await this.refresh())) res = await send();
    if (!res.ok) throw await toError(res);
    return (await res.json()) as T;
  }

  /** Authenticated binary download (artifact zip). */
  async blob(path: string): Promise<Blob> {
    if (this.access === null) await this.refresh();
    const res = await this.fetchImpl(this.base + path, {
      headers: { ...this.orgHeader(), ...(this.access ? { Authorization: `Bearer ${this.access}` } : {}) },
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
