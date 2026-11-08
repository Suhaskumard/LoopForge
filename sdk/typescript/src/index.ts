/**
 * LoopForge TypeScript SDK (Phase 18). Zero runtime dependencies; uses the global `fetch` (Node >= 18, browsers).
 * Same behaviour as the Python SDK: retries 429 (honouring Retry-After) and 502/503/504, POSTs only retried
 * when they carry an Idempotency-Key (create/start/publish generate one), paginated async iterators, typed errors.
 */

export const VERSION = "1.0.0rc1";
export const TERMINAL = ["COMPLETED", "FAILED", "ESCALATED", "CANCELLED"] as const;
const RETRY_STATUS = new Set([429, 502, 503, 504]);

export type Json = Record<string, any>;

/** (HTTP method, path template) of every operation with a named method; the contract test checks it against docs/openapi.json. */
export const OPERATIONS: Record<string, [string, string]> = {
  register: ["POST", "/api/v1/auth/register"],
  login: ["POST", "/api/v1/auth/login"],
  refresh: ["POST", "/api/v1/auth/refresh"],
  me: ["GET", "/api/v1/auth/me"],
  orgs: ["GET", "/api/v1/orgs"],
  org: ["GET", "/api/v1/orgs/{org_id}"],
  usage: ["GET", "/api/v1/orgs/{org_id}/usage"],
  usageReport: ["GET", "/api/v1/orgs/{org_id}/usage/report"],
  usageReportCsv: ["GET", "/api/v1/orgs/{org_id}/usage/report.csv"],
  members: ["GET", "/api/v1/orgs/{org_id}/members"],
  createToken: ["POST", "/api/v1/orgs/{org_id}/tokens"],
  tokens: ["GET", "/api/v1/orgs/{org_id}/tokens"],
  revokeToken: ["DELETE", "/api/v1/orgs/{org_id}/tokens/{token_id}"],
  createWebhook: ["POST", "/api/v1/orgs/{org_id}/webhooks"],
  webhooks: ["GET", "/api/v1/orgs/{org_id}/webhooks"],
  deleteWebhook: ["DELETE", "/api/v1/orgs/{org_id}/webhooks/{webhook_id}"],
  rotateWebhookSecret: ["POST", "/api/v1/orgs/{org_id}/webhooks/{webhook_id}/rotate"],
  createProject: ["POST", "/api/v1/projects"],
  projects: ["GET", "/api/v1/projects"],
  project: ["GET", "/api/v1/projects/{project_id}"],
  deleteProject: ["DELETE", "/api/v1/projects/{project_id}"],
  createTask: ["POST", "/api/v1/tasks"],
  tasks: ["GET", "/api/v1/tasks"],
  task: ["GET", "/api/v1/tasks/{task_id}"],
  startTask: ["POST", "/api/v1/tasks/{task_id}/start"],
  cancelTask: ["POST", "/api/v1/tasks/{task_id}/cancel"],
  retryTask: ["POST", "/api/v1/tasks/{task_id}/retry"],
  taskEvents: ["GET", "/api/v1/tasks/{task_id}/events"],
  taskReport: ["GET", "/api/v1/tasks/{task_id}/report"],
  taskReportMarkdown: ["GET", "/api/v1/tasks/{task_id}/report.md"],
  taskFiles: ["GET", "/api/v1/tasks/{task_id}/files"],
  publish: ["POST", "/api/v1/tasks/{task_id}/publish"],
  publishes: ["GET", "/api/v1/tasks/{task_id}/publish"],
  health: ["GET", "/health"],
};

export class LoopForgeError extends Error {}
export class TransportError extends LoopForgeError {}
export class APIError extends LoopForgeError {
  // plain fields (not parameter properties): the SDK must run under Node's strip-only TypeScript mode
  status: number;
  detail: string;
  code?: string;
  requestId?: string;
  body?: unknown;
  retryAfter?: number;
  constructor(status: number, detail: string, code?: string, requestId?: string, body?: unknown, retryAfter?: number) {
    super(`HTTP ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.requestId = requestId;
    this.body = body;
    this.retryAfter = retryAfter;
  }
}
export class BadRequest extends APIError {}
export class Unauthorized extends APIError {}
export class Forbidden extends APIError {}
export class NotFound extends APIError {}
export class Conflict extends APIError {}
export class ValidationError extends APIError {}
export class RateLimited extends APIError {}
export class ServerError extends APIError {}

const BY_STATUS: Record<number, typeof APIError> = {
  400: BadRequest, 401: Unauthorized, 403: Forbidden, 404: NotFound, 409: Conflict, 422: ValidationError, 429: RateLimited,
};

export interface Options {
  token?: string;
  orgId?: string;
  maxRetries?: number;
  backoffMs?: number;
  maxBackoffMs?: number;
  fetch?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
}

export interface RequestInitLF {
  json?: unknown;
  form?: Record<string, string>;
  params?: Record<string, string | number | undefined | null>;
  idempotencyKey?: string;
  headers?: Record<string, string>;
}

const newKey = (): string => globalThis.crypto.randomUUID().replaceAll("-", "");

export class LoopForge {
  token?: string;
  orgId?: string;
  private base: string;
  private maxRetries: number;
  private backoffMs: number;
  private maxBackoffMs: number;
  private f: typeof fetch;
  private sleep: (ms: number) => Promise<void>;

  constructor(baseUrl: string, opts: Options = {}) {
    this.base = baseUrl.replace(/\/+$/, "");
    this.token = opts.token;
    this.orgId = opts.orgId;
    this.maxRetries = opts.maxRetries ?? 3;
    this.backoffMs = opts.backoffMs ?? 500;
    this.maxBackoffMs = opts.maxBackoffMs ?? 30_000;
    this.f = opts.fetch ?? globalThis.fetch.bind(globalThis);
    this.sleep = opts.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  }

  private delay(attempt: number, retryAfter?: number): number {
    if (retryAfter !== undefined) return Math.min(Math.max(retryAfter * 1000, 0), this.maxBackoffMs);
    return Math.min(this.backoffMs * 2 ** attempt, this.maxBackoffMs);
  }

  /** Send a request with retries; throws an `APIError` subclass for a non-2xx final answer. */
  async request(method: string, path: string, init: RequestInitLF = {}): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json", ...(init.headers ?? {}) };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (this.orgId) headers["X-Org-Id"] = this.orgId;
    if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
    let body: string | undefined;
    if (init.json !== undefined) {
      body = JSON.stringify(init.json);
      headers["Content-Type"] = "application/json";
    } else if (init.form) {
      body = new URLSearchParams(init.form).toString();
      headers["Content-Type"] = "application/x-www-form-urlencoded";
    }
    const query = new URLSearchParams();
    for (const [k, v] of Object.entries(init.params ?? {})) if (v !== undefined && v !== null) query.set(k, String(v));
    const url = `${this.base}${path}${query.size ? `?${query}` : ""}`;
    const retryable = method.toUpperCase() !== "POST" || Boolean(init.idempotencyKey);
    for (let attempt = 0; ; attempt++) {
      let resp: Response;
      try {
        resp = await this.f(url, { method, headers, body });
      } catch (e) {
        if (retryable && attempt < this.maxRetries) {
          await this.sleep(this.delay(attempt));
          continue;
        }
        throw new TransportError(`cannot reach ${this.base}: ${(e as Error).name}`);
      }
      const ra = resp.headers.get("Retry-After");
      const retryAfter = ra !== null && !Number.isNaN(Number(ra)) ? Number(ra) : undefined;
      if (RETRY_STATUS.has(resp.status) && retryable && attempt < this.maxRetries) {
        await this.sleep(this.delay(attempt, retryAfter));
        continue;
      }
      if (resp.ok) return resp;
      throw await apiError(resp, retryAfter);
    }
  }

  private async json<T = any>(method: string, path: string, init: RequestInitLF = {}): Promise<T> {
    const resp = await this.request(method, path, init);
    const text = await resp.text();
    return (text ? JSON.parse(text) : null) as T;
  }

  /** Yield every item of a collection endpoint, following limit/offset. */
  async *paginate(path: string, params: RequestInitLF["params"] = {}, pageSize = 100): AsyncGenerator<Json> {
    let offset = 0;
    for (;;) {
      const resp = await this.request("GET", path, { params: { ...params, limit: pageSize, offset } });
      const items = (await resp.json()) as Json[];
      yield* items;
      offset += items.length;
      const total = resp.headers.get("X-Total-Count");
      if (!items.length || items.length < pageSize || (total !== null && offset >= Number(total))) return;
    }
  }

  private org(orgId?: string): string {
    const id = orgId ?? this.orgId;
    if (!id) throw new Error("this call needs an organization: pass orgId or set LoopForge(url, {orgId})");
    return id;
  }

  // ---- auth ----
  register(email: string, password: string): Promise<Json> {
    return this.json("POST", "/api/v1/auth/register", { json: { email, password } });
  }
  async login(email: string, password: string, mfaCode?: string): Promise<Json> {
    const form: Record<string, string> = { username: email, password };
    if (mfaCode) form.mfa_code = mfaCode;
    const tokens = await this.json("POST", "/api/v1/auth/login", { form });
    this.token = tokens.access_token;
    return tokens;
  }
  async refresh(refreshToken: string): Promise<Json> {
    const tokens = await this.json("POST", "/api/v1/auth/refresh", { json: { refresh_token: refreshToken } });
    this.token = tokens.access_token;
    return tokens;
  }
  me(): Promise<Json> { return this.json("GET", "/api/v1/auth/me"); }
  health(): Promise<Json> { return this.json("GET", "/health"); }

  // ---- organizations ----
  orgs(): Promise<Json[]> { return this.json("GET", "/api/v1/orgs"); }
  async getOrg(orgId?: string): Promise<Json> { return this.json("GET", `/api/v1/orgs/${this.org(orgId)}`); }
  async usage(orgId?: string): Promise<Json> { return this.json("GET", `/api/v1/orgs/${this.org(orgId)}/usage`); }
  async usageReport(o: { groupBy?: string; since?: string; until?: string; orgId?: string } = {}): Promise<Json> {
    return this.json("GET", `/api/v1/orgs/${this.org(o.orgId)}/usage/report`, {
      params: { group_by: o.groupBy ?? "project", from: o.since, to: o.until },
    });
  }
  async usageReportCsv(o: { groupBy?: string; since?: string; until?: string; orgId?: string } = {}): Promise<string> {
    const r = await this.request("GET", `/api/v1/orgs/${this.org(o.orgId)}/usage/report.csv`, {
      params: { group_by: o.groupBy ?? "project", from: o.since, to: o.until },
    });
    return r.text();
  }
  async *members(orgId?: string): AsyncGenerator<Json> { yield* this.paginate(`/api/v1/orgs/${this.org(orgId)}/members`); }
  async createToken(name: string, scope = "developer", expiresDays?: number, orgId?: string): Promise<Json> {
    return this.json("POST", `/api/v1/orgs/${this.org(orgId)}/tokens`, {
      json: { name, scope, expires_days: expiresDays ?? null },
    });
  }
  async *tokens(orgId?: string): AsyncGenerator<Json> { yield* this.paginate(`/api/v1/orgs/${this.org(orgId)}/tokens`); }
  async revokeToken(tokenId: string, orgId?: string): Promise<void> {
    await this.request("DELETE", `/api/v1/orgs/${this.org(orgId)}/tokens/${tokenId}`);
  }
  async createWebhook(url: string, events: string[] = [], format = "json", orgId?: string): Promise<Json> {
    return this.json("POST", `/api/v1/orgs/${this.org(orgId)}/webhooks`, { json: { url, events, format } });
  }
  async *webhooks(orgId?: string): AsyncGenerator<Json> { yield* this.paginate(`/api/v1/orgs/${this.org(orgId)}/webhooks`); }
  async deleteWebhook(id: string, orgId?: string): Promise<void> {
    await this.request("DELETE", `/api/v1/orgs/${this.org(orgId)}/webhooks/${id}`);
  }
  async rotateWebhookSecret(id: string, orgId?: string): Promise<Json> {
    return this.json("POST", `/api/v1/orgs/${this.org(orgId)}/webhooks/${id}/rotate`);
  }

  // ---- projects and tasks ----
  createProject(name: string, fields: Json = {}, idempotencyKey?: string): Promise<Json> {
    return this.json("POST", "/api/v1/projects", { json: { name, ...fields }, idempotencyKey: idempotencyKey ?? newKey() });
  }
  projects(): AsyncGenerator<Json> { return this.paginate("/api/v1/projects"); }
  project(id: string): Promise<Json> { return this.json("GET", `/api/v1/projects/${id}`); }
  async deleteProject(id: string): Promise<void> { await this.request("DELETE", `/api/v1/projects/${id}`); }
  createTask(projectId: string, requirement: string, fields: Json = {}, idempotencyKey?: string): Promise<Json> {
    return this.json("POST", "/api/v1/tasks", {
      json: { project_id: projectId, requirement, ...fields },
      idempotencyKey: idempotencyKey ?? newKey(),
    });
  }
  tasks(filters: RequestInitLF["params"] = {}): AsyncGenerator<Json> { return this.paginate("/api/v1/tasks", filters); }
  task(id: string): Promise<Json> { return this.json("GET", `/api/v1/tasks/${id}`); }
  startTask(id: string, idempotencyKey?: string): Promise<Json> {
    return this.json("POST", `/api/v1/tasks/${id}/start`, { idempotencyKey: idempotencyKey ?? newKey() });
  }
  cancelTask(id: string): Promise<Json> { return this.json("POST", `/api/v1/tasks/${id}/cancel`); }
  retryTask(id: string): Promise<Json> { return this.json("POST", `/api/v1/tasks/${id}/retry`); }
  taskEvents(id: string): AsyncGenerator<Json> { return this.paginate(`/api/v1/tasks/${id}/events`, {}, 500); }
  taskReport(id: string): Promise<Json> { return this.json("GET", `/api/v1/tasks/${id}/report`); }
  async taskReportMarkdown(id: string): Promise<string> {
    return (await this.request("GET", `/api/v1/tasks/${id}/report.md`)).text();
  }
  taskFiles(id: string): Promise<Json[]> { return this.json("GET", `/api/v1/tasks/${id}/files`); }
  publish(taskId: string, repo: string, baseBranch = "main", idempotencyKey?: string): Promise<Json> {
    return this.json("POST", `/api/v1/tasks/${taskId}/publish`, {
      json: { repo, base_branch: baseBranch },
      idempotencyKey: idempotencyKey ?? newKey(),
    });
  }
  publishes(taskId: string): AsyncGenerator<Json> { return this.paginate(`/api/v1/tasks/${taskId}/publish`); }

  /** Poll until the task reaches a terminal status; rejects with Error("timeout") otherwise. */
  async waitForTask(id: string, o: { timeoutMs?: number; pollMs?: number } = {}): Promise<Json> {
    const deadline = Date.now() + (o.timeoutMs ?? 1_800_000);
    for (;;) {
      const t = await this.task(id);
      if ((TERMINAL as readonly string[]).includes(t.status)) return t;
      if (Date.now() >= deadline) throw new Error(`task ${id} still ${t.status} after timeout`);
      await this.sleep(o.pollMs ?? 3000);
    }
  }
}

async function apiError(resp: Response, retryAfter?: number): Promise<APIError> {
  let code: string | undefined;
  let message: string | undefined;
  let body: unknown;
  const text = await resp.text();
  try {
    body = JSON.parse(text);
  } catch {
    message = text.slice(0, 300);
  }
  if (body && typeof body === "object") {
    const b = body as Json;
    if (b.error && typeof b.error === "object") ({ code, message } = b.error);
    else if (b.detail !== undefined) message = String(b.detail);
  }
  const Cls = BY_STATUS[resp.status] ?? (resp.status >= 500 ? ServerError : APIError);
  return new Cls(resp.status, message ?? resp.statusText, code, resp.headers.get("X-Request-ID") ?? undefined, body, retryAfter);
}
