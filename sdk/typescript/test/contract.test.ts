// Contract tests: the TypeScript SDK against a LIVE LoopForge server (started by scripts/ts_sdk_contract.sh).
// Run via `npm test` with LOOPFORGE_URL set. A missing server is a FAILURE, never a silent skip.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  APIError, Conflict, LoopForge, NotFound, OPERATIONS, RateLimited, TransportError, Unauthorized, ValidationError, VERSION,
} from "../src/index.ts";

const URL = process.env.LOOPFORGE_URL;
if (!URL) throw new Error("LOOPFORGE_URL is not set: run sdk/typescript tests through scripts/ts_sdk_contract.sh");
const spec = JSON.parse(readFileSync(new globalThis.URL("../../../docs/openapi.json", import.meta.url), "utf-8"));
const noSleep = async () => {};
const unique = () => `ts-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

async function signedIn(): Promise<LoopForge> {
  const lf = new LoopForge(URL!, { sleep: noSleep });
  const email = `${unique()}@example.com`;
  await lf.register(email, "password123");
  await lf.login(email, "password123");
  lf.orgId = (await lf.orgs())[0].id;
  return lf;
}

test("every named operation exists in the committed OpenAPI with the right method", () => {
  for (const [name, [method, path]] of Object.entries(OPERATIONS)) {
    assert.ok(spec.paths[path], `${name}: ${path} is not in the API`);
    assert.ok(spec.paths[path][method.toLowerCase()], `${name}: ${method} ${path} does not exist`);
  }
});

test("the TypeScript and Python SDKs name exactly the same operations", () => {
  const py = readFileSync(new globalThis.URL("../../python/loopforge_sdk/client.py", import.meta.url), "utf-8");
  const pyOps = new Set([...py.matchAll(/\("(GET|POST|PUT|PATCH|DELETE)", "([^"]+)"\)/g)].map((m) => `${m[1]} ${m[2]}`));
  const tsOps = new Set(Object.values(OPERATIONS).map(([m, p]) => `${m} ${p}`));
  assert.deepEqual([...tsOps].sort(), [...pyOps].sort());
});

test("version matches the server", async () => {
  const lf = new LoopForge(URL!);
  const h = await lf.health();
  assert.equal(h.status, "ok");
  assert.equal(String(h.version).replace("-", ""), VERSION);
});

test("task lifecycle through the SDK", async () => {
  const lf = await signedIn();
  const project = await lf.createProject("billing");
  const task = await lf.createTask(project.id, "Add an invoice export endpoint with tests");
  assert.equal(task.status, "PENDING");
  assert.equal((await lf.task(task.id)).id, task.id);
  const listed: string[] = [];
  for await (const t of lf.tasks()) listed.push(t.id);
  assert.deepEqual(listed, [task.id]);
  assert.equal((await lf.cancelTask(task.id)).status, "CANCELLED");
  assert.equal((await lf.me()).email.endsWith("@example.com"), true);
});

test("pagination follows pages without gaps or repeats", async () => {
  const lf = await signedIn();
  const names = Array.from({ length: 7 }, (_, i) => `p${i}`);
  for (const n of names) await lf.createProject(n);
  const got: string[] = [];
  for await (const p of lf.paginate("/api/v1/projects", {}, 3)) got.push(p.name);
  assert.deepEqual(got.sort(), [...names].sort());
});

test("idempotency key makes a create safe to retry; a different body is rejected", async () => {
  const lf = await signedIn();
  const key = unique();
  const a = await lf.createProject("once", {}, key);
  const b = await lf.createProject("once", {}, key);
  assert.equal(a.id, b.id);
  let n = 0;
  for await (const p of lf.projects()) if (p.name === "once") n++;
  assert.equal(n, 1);
  await assert.rejects(() => lf.createProject("other", {}, key), ValidationError);
});

test("errors map to typed exceptions with status, code and request id", async () => {
  const lf = await signedIn();
  await assert.rejects(() => lf.task("00000000-0000-0000-0000-000000000000"), (e: unknown) => {
    assert.ok(e instanceof NotFound);
    assert.equal((e as NotFound).status, 404);
    assert.equal((e as NotFound).code, "not_found");
    assert.ok((e as NotFound).requestId);
    return true;
  });
  await assert.rejects(() => new LoopForge(URL!).me(), Unauthorized);
  await assert.rejects(() => lf.request("GET", "/api/v1/nope"), APIError);
});

test("usage report, CSV, tokens and webhook helpers", async () => {
  const lf = await signedIn();
  assert.equal((await lf.usage()).tasks_created, 0);
  assert.equal((await lf.usageReport({ groupBy: "agent" })).totals.tokens, 0);
  assert.match((await lf.usageReportCsv()).split("\n")[0], /^period_from,period_to,group_by/);
  const tok = await lf.createToken("ci", "viewer");
  assert.ok(tok.token.startsWith("lfk_"));
  await lf.revokeToken(tok.id);
  const members: string[] = [];
  for await (const m of lf.members()) members.push(m.email);
  assert.equal(members.length, 1);
});

test("API-token rate limit is retried with Retry-After then surfaces as RateLimited", async () => {
  const lf = await signedIn();
  const tok = await lf.createToken("limited", "developer");
  const waits: number[] = [];
  const bot = new LoopForge(URL!, { token: tok.token, maxRetries: 1, sleep: async (ms) => void waits.push(ms) });
  // the server's per-token limit is set by the runner script (3 per minute)
  for (let i = 0; i < 3; i++) for await (const _ of bot.projects()) void _;
  await assert.rejects(async () => { for await (const _ of bot.projects()) void _; }, RateLimited);
  assert.equal(waits.length, 1);
  assert.ok(waits[0] >= 1000, `should honour Retry-After, waited ${waits[0]}ms`);
});

test("POST without an idempotency key is never retried; transport errors surface", async () => {
  let calls = 0;
  const failing = (async () => { calls++; return new Response("{}", { status: 503 }); }) as unknown as typeof fetch;
  const c = new LoopForge("http://x", { fetch: failing, sleep: noSleep });
  await assert.rejects(() => c.request("POST", "/x", { json: {} }), APIError);
  assert.equal(calls, 1);
  calls = 0;
  await assert.rejects(() => c.request("POST", "/x", { json: {}, idempotencyKey: "k" }), APIError);
  assert.equal(calls, 4);
  const down = (async () => { throw new TypeError("refused"); }) as unknown as typeof fetch;
  await assert.rejects(() => new LoopForge("http://x", { fetch: down, sleep: noSleep, maxRetries: 1 }).health(), TransportError);
});

test("waitForTask polls to a terminal state and times out; org-less calls explain themselves", async () => {
  const states = ["PLANNING", "BUILDING", "COMPLETED"];
  const f = (async () => new Response(JSON.stringify({ status: states.shift() }), { status: 200 })) as unknown as typeof fetch;
  const c = new LoopForge("http://x", { fetch: f, sleep: noSleep });
  assert.equal((await c.waitForTask("t", { pollMs: 0 })).status, "COMPLETED");
  const stuck = (async () => new Response('{"status":"BUILDING"}', { status: 200 })) as unknown as typeof fetch;
  await assert.rejects(() => new LoopForge("http://x", { fetch: stuck, sleep: noSleep }).waitForTask("t", { timeoutMs: 0 }), /still BUILDING/);
  await assert.rejects(() => c.usage(), /needs an organization/);
  const conflict = (async () => new Response('{"detail":"plain"}', { status: 409 })) as unknown as typeof fetch;
  await assert.rejects(() => new LoopForge("http://x", { fetch: conflict, sleep: noSleep }).request("GET", "/x"), Conflict);
});
